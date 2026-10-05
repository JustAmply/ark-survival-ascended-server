# ADR-0001: Configure the server through discrete environment variables

- Status: Accepted
- Date: 2026-08-28

## Context

The server was configured through a single environment variable,
`ASA_START_PARAMS`, holding the entire launch line:

```yaml
ASA_START_PARAMS: >
  TheIsland_WP?listen?Port=7777?RCONPort=27020?RCONEnabled=True?ServerAdminPassword=change_this_password
  -WinLiveMaxPlayers=50 -clusterid=default -ClusterDirOverride="/home/gameserver/cluster-shared"
```

This has three problems:

1. **Nothing can be changed in isolation.** Rotating the admin password or
   moving the RCON port means editing a long YAML folded scalar by hand, which
   is where most reported misconfigurations came from.
2. **No per-setting composition.** Compose users cannot put one setting in an
   `.env` file, a secret, or a per-environment override.
3. **The string was parsed by substring search.** `AsaSettings` located a value
   with `str.find("Key=")`, so asking for `Port` could return the value of
   `RCONPort`.

Meanwhile a large installed base runs the current `docker-compose.yml` verbatim,
including third-party stacks and copy-pasted forum configurations. Breaking them
is not acceptable.

## Decision

Introduce discrete `ASA_*` environment variables for the settings people
actually change (`ASA_MAP`, `ASA_PORT`, `ASA_RCON_PORT`, `ASA_RCON_ENABLED`,
`ASA_SERVER_ADMIN_PASSWORD`, `ASA_SERVER_PASSWORD`, `ASA_SPECTATOR_PASSWORD`,
`ASA_SESSION_NAME`, `ASA_MAX_PLAYERS`, `ASA_CLUSTER_ID`, `ASA_CLUSTER_DIR`,
`ASA_MODS`, `ASA_BATTLEYE`), plus `ASA_EXTRA_QUERY_PARAMS` and
`ASA_EXTRA_FLAGS` as escape hatches for everything else.

`ASA_START_PARAMS` remains fully supported and becomes the **base launch line**.
Discrete variables form an **overlay** applied on top of it.

Backward compatibility is achieved **structurally, not conditionally**. A single
module, `LaunchConfiguration`, parses a launch line in a structure-preserving way
— unknown tokens carried through verbatim, key order never rearranged — so that:

```
parse(line).render() == line
```

When no discrete variable is set, no overlay is applied and the launch line is
rendered straight back out. Existing stacks therefore launch the identical
process, and that property is covered by a round-trip test rather than by a
branch that could rot.

## Alternatives considered

**A second code path for legacy stacks.** Pass `ASA_START_PARAMS` through
untouched when no discrete variable is set, and build from scratch otherwise.
Rejected: two paths means the legacy path stops being exercised by the tests
that matter, and every future change has to be made twice.

**A config file (YAML/TOML) mounted into the container.** Rejected: it adds a
file to mount and a parser to maintain for a project with a deliberate
zero-dependency policy, and it fits Docker Compose worse than environment
variables do.

**Deprecating `ASA_START_PARAMS`.** Rejected: it is the only reasonable way to
express the long tail of ARK launch options, and it is what every existing guide
and forum post tells people to use. It stays a first-class input.

## Consequences

- Compose stacks can set one variable at a time, use `.env` files, and keep the
  admin password out of the compose file.
- `asa-ctrl rcon` discovers the password and port from the discrete variables as
  well, because RCON discovery reads through the same module.
- Precedence is fixed and must be documented wherever these variables are
  listed: `ASA_EXTRA_*` > named `ASA_*` > `ASA_START_PARAMS` > built-in defaults.
- Adding a new setting is a one-line table entry in `launch_config.py`; the
  launcher, the CLI and RCON discovery all pick it up.
- Mod ids from `mods.json` are now merged into a single `-mods=` flag instead of
  appending a second one. This changes behaviour for stacks that had both a
  `-mods=` flag in their start params and entries in `mods.json`; previously the
  game binary received two conflicting flags.
