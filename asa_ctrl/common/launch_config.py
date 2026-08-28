"""The launch line contract for the ARK dedicated server.

A *launch line* is the argument string handed to ``ArkAscendedServer.exe``::

    TheIsland_WP?listen?Port=7777?RCONPort=27020 -WinLiveMaxPlayers=50 -nosteam
    \\_________/ \\____________________________/  \\_________________________/
      map name          query segment                      flags

This module owns that contract end to end: parsing an existing launch line,
overlaying discrete ``ASA_*`` environment variables on top of it, answering
lookups (``ServerAdminPassword``, ``RCONPort``, ...) and rendering the result
back into a launch line.

Parsing is structure preserving: unknown tokens are carried through verbatim and
key order is never rearranged. As a consequence ``parse(line).render() == line``
for any launch line that does not get an overlay applied, which is what keeps
existing stacks byte-for-byte unaffected.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .constants import DEFAULT_LAUNCH_BASE


TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
FALSE_VALUES = frozenset({"0", "false", "no", "off"})

# Discrete environment variables that overlay a single entry of the query
# segment. Order matters only for readability; each entry is independent.
QUERY_ENV_OVERRIDES: Tuple[Tuple[str, str], ...] = (
    ("ASA_SESSION_NAME", "SessionName"),
    ("ASA_PORT", "Port"),
    ("ASA_RCON_PORT", "RCONPort"),
    ("ASA_RCON_ENABLED", "RCONEnabled"),
    ("ASA_SERVER_ADMIN_PASSWORD", "ServerAdminPassword"),
    ("ASA_SERVER_PASSWORD", "ServerPassword"),
    ("ASA_SPECTATOR_PASSWORD", "SpectatorPassword"),
    ("ASA_MAX_PLAYERS_QUERY", "MaxPlayers"),
)

# Discrete environment variables that overlay a single ``-Key=Value`` flag.
FLAG_ENV_OVERRIDES: Tuple[Tuple[str, str], ...] = (
    ("ASA_MAX_PLAYERS", "WinLiveMaxPlayers"),
    ("ASA_CLUSTER_ID", "clusterid"),
    ("ASA_CLUSTER_DIR", "ClusterDirOverride"),
    ("ASA_MODS", "mods"),
)

# Every variable that participates in the discrete configuration overlay. When
# none of these is set the legacy ``ASA_START_PARAMS`` value is passed through
# untouched.
LAUNCH_ENV_VARS: Tuple[str, ...] = (
    ("ASA_MAP",)
    + tuple(name for name, _ in QUERY_ENV_OVERRIDES)
    + tuple(name for name, _ in FLAG_ENV_OVERRIDES)
    + ("ASA_BATTLEYE", "ASA_EXTRA_QUERY_PARAMS", "ASA_EXTRA_FLAGS")
)

MODS_FLAG = "mods"
NO_BATTLEYE_FLAG = "NoBattlEye"


def coerce_bool(value: Optional[str], default: bool = False) -> bool:
    """Interpret an environment value as a boolean."""
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    return default


def coerce_int(value: Optional[str], default: int) -> int:
    """Interpret an environment value as an integer, falling back on default."""
    if not value:
        return default
    try:
        return int(value.strip())
    except (TypeError, ValueError):
        return default


def _render_ark_bool(value: str) -> str:
    """Normalize truthy/falsy spellings to the ``True``/``False`` ARK expects."""
    normalized = value.strip().lower()
    if normalized in TRUE_VALUES:
        return "True"
    if normalized in FALSE_VALUES:
        return "False"
    return value.strip()


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def tokenize(line: str) -> List[str]:
    """Split a launch line on whitespace while keeping quoted spans intact.

    Quote characters are retained inside the token so that rendering reproduces
    the original text exactly; ``shlex.split`` removes them at launch time.
    """
    tokens: List[str] = []
    current: List[str] = []
    quote: Optional[str] = None

    for char in line:
        if quote is not None:
            current.append(char)
            if char == quote:
                quote = None
        elif char in "\"'":
            quote = char
            current.append(char)
        elif char.isspace():
            if current:
                tokens.append("".join(current))
                current = []
        else:
            current.append(char)

    if current:
        tokens.append("".join(current))
    return tokens


@dataclass
class QueryEntry:
    """One ``?``-separated entry of the query segment.

    ``value`` is ``None`` for bare switches such as ``?listen``.
    """

    key: str
    value: Optional[str] = None

    def render(self) -> str:
        if self.value is None:
            return self.key
        return f"{self.key}={self.value}"


@dataclass
class LaunchConfiguration:
    """Structured, order-preserving model of a launch line."""

    map_name: str = ""
    query: List[QueryEntry] = field(default_factory=list)
    flags: List[str] = field(default_factory=list)

    # -- construction ----------------------------------------------------

    @classmethod
    def parse(cls, line: Optional[str]) -> "LaunchConfiguration":
        """Parse a launch line into its map name, query segment and flags."""
        tokens = tokenize((line or "").strip())
        if not tokens:
            return cls()

        map_name = ""
        query: List[QueryEntry] = []
        flags: List[str] = list(tokens)

        if not tokens[0].startswith("-"):
            head, *flags = tokens
            segments = head.split("?")
            map_name = segments[0]
            for segment in segments[1:]:
                if not segment:
                    continue
                if "=" in segment:
                    key, value = segment.split("=", 1)
                    query.append(QueryEntry(key, value))
                else:
                    query.append(QueryEntry(segment, None))

        return cls(map_name=map_name, query=query, flags=list(flags))

    @classmethod
    def from_env(
        cls, environ: Optional[Mapping[str, str]] = None
    ) -> "LaunchConfiguration":
        """Build the effective configuration from the process environment.

        ``ASA_START_PARAMS`` provides the base launch line; discrete ``ASA_*``
        variables are overlaid on top of it. When no discrete variable is set the
        base is returned untouched, so existing stacks keep their exact launch
        line.
        """
        environ = os.environ if environ is None else environ
        base = (environ.get("ASA_START_PARAMS") or "").strip()
        overlay_present = any(_is_set(environ, name) for name in LAUNCH_ENV_VARS)

        if not base and overlay_present:
            base = DEFAULT_LAUNCH_BASE

        config = cls.parse(base)
        if overlay_present:
            config.apply_environment_overlay(environ)
        return config

    # -- inspection ------------------------------------------------------

    def is_empty(self) -> bool:
        return not self.map_name and not self.query and not self.flags

    def query_value(self, key: str) -> Optional[str]:
        """Return the value of a query entry, or ``None`` when absent/bare."""
        target = key.lower()
        for entry in self.query:
            if entry.key.lower() == target and entry.value is not None:
                return _strip_quotes(entry.value)
        return None

    def flag_value(self, key: str) -> Optional[str]:
        """Return the value of a ``-Key=Value`` flag, or ``None`` when absent."""
        prefix = f"-{key}=".lower()
        for token in self.flags:
            if token.lower().startswith(prefix):
                return _strip_quotes(token[len(prefix):])
        return None

    def value(self, key: str) -> Optional[str]:
        """Look a setting up in the query segment first, then in the flags."""
        found = self.query_value(key)
        if found is not None:
            return found
        return self.flag_value(key)

    def has_flag(self, key: str) -> bool:
        """Report whether a bare or valued flag with this name is present."""
        name = key.lstrip("-").lower()
        for token in self.flags:
            candidate = token.lstrip("-").split("=", 1)[0].lower()
            if candidate == name:
                return True
        return False

    def as_mapping(self) -> Dict[str, str]:
        """Flatten into a plain mapping (map name under the ``_map`` key)."""
        result: Dict[str, str] = {"_map": self.map_name}
        for entry in self.query:
            if entry.value is not None:
                result[entry.key] = _strip_quotes(entry.value)
        for token in self.flags:
            if token.startswith("-") and "=" in token:
                key, value = token[1:].split("=", 1)
                result[key] = _strip_quotes(value)
        return result

    # -- mutation --------------------------------------------------------

    def set_query(self, key: str, value: Optional[str]) -> None:
        """Set a query entry in place, keeping its original position."""
        target = key.lower()
        replaced = False
        remaining: List[QueryEntry] = []
        for entry in self.query:
            if entry.key.lower() != target:
                remaining.append(entry)
                continue
            if replaced:
                continue  # drop duplicates of the key we just set
            entry.value = value
            remaining.append(entry)
            replaced = True
        self.query = remaining
        if not replaced:
            self.query.append(QueryEntry(key, value))

    def set_flag(self, key: str, value: str) -> None:
        """Set a ``-Key=Value`` flag in place, keeping its original position."""
        prefix = f"-{key}=".lower()
        rendered = f"-{key}={value}"
        replaced = False
        remaining: List[str] = []
        for token in self.flags:
            if not token.lower().startswith(prefix):
                remaining.append(token)
                continue
            if replaced:
                continue
            remaining.append(rendered)
            replaced = True
        self.flags = remaining
        if not replaced:
            self.flags.append(rendered)

    def ensure_flag(self, token: str) -> None:
        """Append a bare flag unless a flag with that name is already present."""
        if not self.has_flag(token):
            self.flags.append(token if token.startswith("-") else f"-{token}")

    def remove_flag(self, key: str) -> None:
        """Remove every bare or valued flag with this name."""
        name = key.lstrip("-").lower()
        self.flags = [
            token
            for token in self.flags
            if token.lstrip("-").split("=", 1)[0].lower() != name
        ]

    def mod_ids(self) -> List[str]:
        """Return the mod ids currently carried by the ``-mods=`` flag."""
        raw = self.flag_value(MODS_FLAG)
        if not raw:
            return []
        return [part.strip() for part in raw.split(",") if part.strip()]

    def merge_mods(self, mod_ids: Iterable[object]) -> None:
        """Fold additional mod ids into a single ``-mods=`` flag.

        Existing ids keep their order and position; duplicates are dropped. This
        replaces the previous behaviour of appending a second ``-mods=`` flag,
        which left the game binary with two conflicting values.
        """
        merged = self.mod_ids()
        for mod_id in mod_ids:
            candidate = str(mod_id).strip()
            if candidate and candidate not in merged:
                merged.append(candidate)
        if merged:
            self.set_flag(MODS_FLAG, ",".join(merged))

    def apply_environment_overlay(self, environ: Mapping[str, str]) -> None:
        """Overlay discrete ``ASA_*`` variables onto this configuration.

        Named variables are applied first, then the ``ASA_EXTRA_*`` escape
        hatches, so a raw extra can override a named one.
        """
        map_name = _value_of(environ, "ASA_MAP")
        if map_name is not None:
            self.map_name = map_name

        for env_name, key in QUERY_ENV_OVERRIDES:
            value = _value_of(environ, env_name)
            if value is None:
                continue
            if env_name == "ASA_RCON_ENABLED":
                value = _render_ark_bool(value)
            self.set_query(key, value)

        for env_name, key in FLAG_ENV_OVERRIDES:
            value = _value_of(environ, env_name)
            if value is not None:
                self.set_flag(key, value)

        battleye = _value_of(environ, "ASA_BATTLEYE")
        if battleye is not None:
            if coerce_bool(battleye, default=True):
                self.remove_flag(NO_BATTLEYE_FLAG)
            else:
                self.ensure_flag(f"-{NO_BATTLEYE_FLAG}")

        extra_query = _value_of(environ, "ASA_EXTRA_QUERY_PARAMS")
        if extra_query is not None:
            self._apply_extra_query(extra_query)

        extra_flags = _value_of(environ, "ASA_EXTRA_FLAGS")
        if extra_flags is not None:
            self._apply_extra_flags(extra_flags)

    def _apply_extra_query(self, raw: str) -> None:
        for segment in raw.strip().lstrip("?").split("?"):
            segment = segment.strip()
            if not segment:
                continue
            if "=" in segment:
                key, value = segment.split("=", 1)
                self.set_query(key, value)
            else:
                self.set_query(segment, None)

    def _apply_extra_flags(self, raw: str) -> None:
        for token in tokenize(raw):
            if not token:
                continue
            if token.startswith("-") and "=" in token:
                key, value = token[1:].split("=", 1)
                self.set_flag(key, value)
            else:
                name = token.lstrip("-")
                self.remove_flag(name)
                self.flags.append(token if token.startswith("-") else f"-{token}")

    # -- rendering -------------------------------------------------------

    def render(self) -> str:
        """Render the configuration back into a launch line."""
        head = self.map_name
        for entry in self.query:
            head = f"{head}?{entry.render()}"
        parts: List[str] = [head] if head else []
        parts.extend(self.flags)
        return " ".join(part for part in parts if part)

    def __str__(self) -> str:  # pragma: no cover - convenience only
        return self.render()


def _value_of(environ: Mapping[str, str], name: str) -> Optional[str]:
    """Return a stripped environment value, treating blanks as unset."""
    raw = environ.get(name)
    if raw is None:
        return None
    stripped = raw.strip()
    return stripped or None


def _is_set(environ: Mapping[str, str], name: str) -> bool:
    return _value_of(environ, name) is not None


def discrete_env_vars() -> Sequence[str]:
    """Names of every environment variable feeding the discrete overlay."""
    return LAUNCH_ENV_VARS


__all__ = [
    "LaunchConfiguration",
    "QueryEntry",
    "coerce_bool",
    "coerce_int",
    "discrete_env_vars",
    "tokenize",
    "LAUNCH_ENV_VARS",
    "QUERY_ENV_OVERRIDES",
    "FLAG_ENV_OVERRIDES",
]
