"""ASA Control - ARK: Survival Ascended Server Management Tool.

Refactored Python implementation providing:
* RCON command execution utilities
* Mod database management
* INI / start parameter parsing helpers
* Thin CLI wrapper (`asa-ctrl`)

Public helpers exported here are considered part of the semi-stable API. The
CLI remains the primary user interface; programmatic usage is a nice-to-have.

Names listed in `_DEPRECATED` are resolved lazily from `asa_ctrl._compat` and
warn on access; they will be removed in a future release.
"""

import importlib
import warnings
from typing import TYPE_CHECKING

from .common.logging_config import configure_logging  # noqa: F401
from .core.mods import ModDatabase, format_mod_list_for_server  # noqa: F401
from .core.rcon import execute_rcon_command  # noqa: F401
from .common.config import AsaSettings  # noqa: F401

if TYPE_CHECKING:
	from .core.rcon import RconClient as RconClient
	from ._compat import IniConfigHelper as IniConfigHelper
	from ._compat import StartParamsHelper as StartParamsHelper
	from ._compat import parse_start_params as parse_start_params

__all__ = [
	"configure_logging",
	"ModDatabase",
	"format_mod_list_for_server",
	"execute_rcon_command",
	"RconClient",
	"AsaSettings",
	"StartParamsHelper",
	"IniConfigHelper",
	"parse_start_params",
]

# Deprecated names, mapped to the module that still defines them and the
# replacement each warning should point callers at.
_DEPRECATED = {
	"RconClient": (
		"asa_ctrl.core.rcon",
		"asa_ctrl.execute_rcon_command, or import RconClient from "
		"asa_ctrl.core.rcon for advanced sessions",
	),
	"StartParamsHelper": (
		"asa_ctrl._compat",
		"asa_ctrl.common.launch_config.LaunchConfiguration",
	),
	"IniConfigHelper": (
		"asa_ctrl._compat",
		"asa_ctrl.common.config.parse_ini or asa_ctrl.common.config.AsaSettings",
	),
	"parse_start_params": (
		"asa_ctrl._compat",
		"LaunchConfiguration.parse(...).as_mapping()",
	),
}


def __getattr__(name: str):
	try:
		module_name, replacement = _DEPRECATED[name]
	except KeyError:
		raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None

	warnings.warn(
		f"asa_ctrl.{name} is deprecated; use {replacement}.",
		DeprecationWarning,
		stacklevel=2,
	)
	return getattr(importlib.import_module(module_name), name)

__version__ = "2.1.0"
__author__ = "JustAmply"
