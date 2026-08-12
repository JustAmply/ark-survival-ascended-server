"""ASA Control - ARK: Survival Ascended Server Management Tool.

Refactored Python implementation providing:
* RCON command execution utilities
* Mod database management
* INI / start parameter parsing helpers
* Thin CLI wrapper (`asa-ctrl`)

Public helpers exported here are considered part of the semi-stable API. The
CLI remains the primary user interface; programmatic usage is a nice-to-have.
"""

import warnings
from typing import TYPE_CHECKING

from .common.logging_config import configure_logging  # noqa: F401
from .core.mods import ModDatabase, format_mod_list_for_server  # noqa: F401
from .core.rcon import execute_rcon_command  # noqa: F401
from .common.config import AsaSettings, StartParamsHelper, IniConfigHelper, parse_start_params  # noqa: F401

if TYPE_CHECKING:
	from .core.rcon import RconClient as RconClient

__all__ = [
	"configure_logging",
	"ModDatabase",
	"format_mod_list_for_server",
	"execute_rcon_command",
	"AsaSettings",
	"StartParamsHelper",
	"IniConfigHelper",
	"parse_start_params",
]


def __getattr__(name: str):
	if name == "RconClient":
		warnings.warn(
			"asa_ctrl.RconClient is deprecated; use asa_ctrl.execute_rcon_command "
			"or import RconClient from asa_ctrl.core.rcon for advanced sessions.",
			DeprecationWarning,
			stacklevel=2,
		)
		from .core.rcon import RconClient

		return RconClient
	raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__version__ = "2.1.0"
__author__ = "JustAmply"
