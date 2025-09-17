"""ASA Control - ARK: Survival Ascended Server Management Tool.

Refactored Python implementation providing:
* RCON command execution utilities
* Mod database management
* INI / start parameter parsing helpers
* Thin CLI wrapper (`asa-ctrl`)
* Enterprise features (configuration, security, monitoring, audit)

Public helpers exported here are considered part of the semi-stable API. The
CLI remains the primary user interface; programmatic usage is a nice-to-have.
"""

from .logging_config import configure_logging  # noqa: F401
from .mods import ModDatabase, format_mod_list_for_server  # noqa: F401
from .rcon import execute_rcon_command, RconClient  # noqa: F401
from .config import StartParamsHelper, IniConfigHelper, parse_start_params  # noqa: F401
from .enterprise import (  # noqa: F401
    get_config_manager,
    get_security_manager,
    get_audit_logger,
    get_health_checker,
    get_metrics_collector,
    EnterpriseConfigManager,
    SecurityManager,
    AuditLogger,
    HealthChecker,
    MetricsCollector,
    ConfigSchema
)
from .api import (  # noqa: F401
    get_api_server,
    start_api_server,
    stop_api_server,
    EnterpriseAPIServer
)
from .backup import get_backup_manager, BackupManager  # noqa: F401

__all__ = [
	"configure_logging",
	"ModDatabase",
	"format_mod_list_for_server",
	"execute_rcon_command",
	"RconClient",
	"StartParamsHelper",
	"IniConfigHelper",
	"parse_start_params",
	# Enterprise features
	"get_config_manager",
	"get_security_manager", 
	"get_audit_logger",
	"get_health_checker",
	"get_metrics_collector",
	"EnterpriseConfigManager",
	"SecurityManager",
	"AuditLogger",
	"HealthChecker",
	"MetricsCollector",
	"ConfigSchema",
	# API features
	"get_api_server",
	"start_api_server",
	"stop_api_server",
	"EnterpriseAPIServer",
	# Backup features
	"get_backup_manager",
	"BackupManager"
]

__version__ = "3.0.0-enterprise"
__author__ = "JustAmply"
