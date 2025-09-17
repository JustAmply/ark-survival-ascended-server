"""
Command Line Interface for ASA Control.

Provides CLI commands for RCON, mod management, and enterprise features.
"""

import argparse
import sys
import os
import json
from typing import List, Optional

from .constants import ExitCodes
from .rcon import execute_rcon_command
from .mods import ModDatabase, format_mod_list_for_server
from .logging_config import configure_logging, get_logger
from .config import parse_start_params
from .errors import (
    RconPasswordNotFoundError, 
    RconAuthenticationError, 
    RconPortNotFoundError,
    ModAlreadyEnabledError,
    CorruptedModsDatabaseError
)
from .enterprise import (
    get_config_manager,
    get_security_manager,
    get_audit_logger,
    get_health_checker,
    get_metrics_collector,
    ConfigValidationError,
    SecurityViolationError,
    HealthCheckError
)


def exit_with_error(message: str, exit_code: int) -> None:
    """
    Print an error message and exit with the specified code.
    
    Args:
        message: The error message to print
        exit_code: The exit code to use
    """
    print(f"Error: {message}", file=sys.stderr)
    sys.exit(exit_code)


class RconCommand:
    """Handles RCON command execution."""
    
    @staticmethod
    def add_parser(subparsers) -> None:
        """Add RCON command parser to subparsers."""
        parser = subparsers.add_parser('rcon', help='Interface for RCON command execution')
        parser.add_argument('--exec', dest='command', required=True, 
                          help='An RCON command to execute')
        parser.set_defaults(func=RconCommand.execute)
    
    @staticmethod
    def execute(args) -> None:
        """Execute an RCON command with enterprise security integration."""
        try:
            # Enterprise security integration
            client_ip = "127.0.0.1"  # Default for local execution
            if hasattr(args, 'client_ip') and args.client_ip:
                client_ip = args.client_ip
            
            # Check security if enterprise features are available
            try:
                security_manager = get_security_manager()
                
                # Check IP access
                if not security_manager.check_rcon_access(client_ip):
                    exit_with_error(
                        f"RCON access denied for IP {client_ip}",
                        ExitCodes.SECURITY_VIOLATION
                    )
                
                # Check rate limiting
                if not security_manager.check_rate_limit(client_ip):
                    exit_with_error(
                        f"RCON rate limit exceeded for IP {client_ip}",
                        ExitCodes.SECURITY_VIOLATION
                    )
                
                # Validate command input
                if not security_manager.validate_input(args.command):
                    exit_with_error(
                        "RCON command blocked by security policy",
                        ExitCodes.SECURITY_VIOLATION
                    )
                
                # Log the command execution
                audit_logger = get_audit_logger()
                audit_logger.log_admin_action("rcon_command", {
                    "command": args.command,
                    "client_ip": client_ip,
                    "user": os.environ.get("USER", "unknown")
                })
                
            except Exception as e:
                # If enterprise features fail, log warning but continue
                logger = get_logger(__name__)
                logger.warning("Enterprise security check failed, proceeding: %s", e)
            
            # Execute the command
            response = execute_rcon_command(args.command)
            print(response)
            
        except RconPasswordNotFoundError:
            exit_with_error(
                "Could not read RCON password. Make sure it is properly configured, either as "
                "start parameter ?ServerAdminPassword=mypass or in GameUserSettings.ini in the "
                "[ServerSettings] section as ServerAdminPassword=mypass",
                ExitCodes.RCON_PASSWORD_NOT_FOUND
            )
        except RconAuthenticationError:
            exit_with_error(
                "Could not execute this RCON command. Authentication failed (wrong server password).",
                ExitCodes.RCON_PASSWORD_WRONG
            )
        except RconPortNotFoundError:
            exit_with_error(
                "Could not find RCON port. Make sure it is properly configured in start parameters "
                "or GameUserSettings.ini",
                ExitCodes.RCON_PASSWORD_NOT_FOUND
            )
        except Exception as e:
            exit_with_error(
                f"Rcon command execution failed: {e}",
                ExitCodes.RCON_COMMAND_EXECUTION_FAILED
            )


class ModsCommand:
    """Handles mod management commands."""
    
    @staticmethod
    def add_parser(subparsers) -> None:
        """Add mods command parser to subparsers."""
        parser = subparsers.add_parser('mods', help='Interface for mod management')
        
        # Add subcommands for mods
        mod_subparsers = parser.add_subparsers(dest='mod_action', help='Mod actions')
        
        # Enable mod command
        enable_parser = mod_subparsers.add_parser('enable', help='Enable a mod')
        enable_parser.add_argument('mod_id', type=int, help='The mod ID to enable')
        
        # Disable mod command
        disable_parser = mod_subparsers.add_parser('disable', help='Disable a mod')
        disable_parser.add_argument('mod_id', type=int, help='The mod ID to disable')
        
        # List mods command
        list_parser = mod_subparsers.add_parser('list', help='List all mods')
        list_parser.add_argument('--enabled-only', action='store_true', 
                               help='Show only enabled mods')
        
        parser.set_defaults(func=ModsCommand.execute)
    
    @staticmethod
    def execute(args) -> None:
        """Execute a mod management command."""
        try:
            if args.mod_action == 'enable':
                ModsCommand._enable_mod(args.mod_id)
            elif args.mod_action == 'disable':
                ModsCommand._disable_mod(args.mod_id)
            elif args.mod_action == 'list':
                ModsCommand._list_mods(args.enabled_only)
            else:
                print("Please specify a mod action: enable, disable, or list")
                sys.exit(ExitCodes.OK)
                
        except CorruptedModsDatabaseError as e:
            exit_with_error(str(e), ExitCodes.CORRUPTED_MODS_DATABASE)
    
    @staticmethod
    def _enable_mod(mod_id: int) -> None:
        """Enable a mod."""
        try:
            db = ModDatabase.get_instance()
            db.enable_mod(mod_id)
            print(f"Enabled mod id '{mod_id}' successfully. The server will download the mod upon startup.")
            
        except ModAlreadyEnabledError:
            exit_with_error(
                "This mod is already enabled! Use 'asa-ctrl mods list' to see what mods are currently enabled.",
                ExitCodes.MOD_ALREADY_ENABLED
            )
    
    @staticmethod
    def _disable_mod(mod_id: int) -> None:
        """Disable a mod."""
        db = ModDatabase.get_instance()
        if db.disable_mod(mod_id):
            print(f"Disabled mod id '{mod_id}' successfully.")
        else:
            print(f"Mod id '{mod_id}' was not found in the database.")
    
    @staticmethod
    def _list_mods(enabled_only: bool = False) -> None:
        """List mods."""
        db = ModDatabase.get_instance()
        
        if enabled_only:
            mods = db.get_enabled_mods()
            print("Enabled mods:")
        else:
            mods = db.get_all_mods()
            print("All mods:")
        
        if not mods:
            print("  No mods found.")
            return
        
        for mod in mods:
            status = "enabled" if mod.enabled else "disabled"
            print(f"  {mod.mod_id}: {mod.name} ({status})")

    @staticmethod
    def print_mods_string(_args) -> None:
        """Print the formatted mods parameter string only."""
        print(format_mod_list_for_server(), end="")


class EnterpriseCommand:
    """Handles enterprise management commands."""
    
    @staticmethod
    def add_parser(subparsers) -> None:
        """Add enterprise command parser."""
        enterprise_parser = subparsers.add_parser(
            'enterprise',
            help='Enterprise management commands'
        )
        enterprise_subparsers = enterprise_parser.add_subparsers(
            dest='enterprise_action',
            help='Enterprise actions'
        )
        
        # Config management
        config_parser = enterprise_subparsers.add_parser(
            'config',
            help='Configuration management'
        )
        config_subparsers = config_parser.add_subparsers(
            dest='config_action',
            help='Configuration actions'
        )
        
        show_config = config_subparsers.add_parser('show', help='Show current configuration')
        show_config.set_defaults(func=EnterpriseCommand.show_config)
        
        update_config = config_subparsers.add_parser('update', help='Update configuration')
        update_config.add_argument('--field', required=True, help='Configuration field to update')
        update_config.add_argument('--value', required=True, help='New value')
        update_config.set_defaults(func=EnterpriseCommand.update_config)
        
        # Health checks
        health_parser = enterprise_subparsers.add_parser('health', help='System health check')
        health_parser.set_defaults(func=EnterpriseCommand.health_check)
        
        # Metrics
        metrics_parser = enterprise_subparsers.add_parser('metrics', help='Collect metrics')
        metrics_parser.set_defaults(func=EnterpriseCommand.collect_metrics)
        
        # Audit logs
        audit_parser = enterprise_subparsers.add_parser('audit', help='Audit log management')
        audit_subparsers = audit_parser.add_subparsers(
            dest='audit_action',
            help='Audit actions'
        )
        
        log_event = audit_subparsers.add_parser('log', help='Log an event')
        log_event.add_argument('--type', required=True, help='Event type')
        log_event.add_argument('--details', required=True, help='Event details (JSON)')
        log_event.set_defaults(func=EnterpriseCommand.log_audit_event)
        
        # Security
        security_parser = enterprise_subparsers.add_parser('security', help='Security management')
        security_subparsers = security_parser.add_subparsers(
            dest='security_action',
            help='Security actions'
        )
        
        check_access = security_subparsers.add_parser('check-access', help='Check IP access')
        check_access.add_argument('--ip', required=True, help='IP address to check')
        check_access.set_defaults(func=EnterpriseCommand.check_ip_access)
    
    @staticmethod
    def show_config(args) -> None:
        """Show current enterprise configuration."""
        try:
            config_manager = get_config_manager()
            config = config_manager.get_config()
            
            print("Enterprise Configuration:")
            print("=" * 50)
            config_dict = config.__dict__
            for key, value in sorted(config_dict.items()):
                if 'password' in key.lower() or 'token' in key.lower():
                    value = "***HIDDEN***" if value else "(not set)"
                print(f"  {key}: {value}")
                
        except ConfigValidationError as e:
            exit_with_error(f"Configuration error: {e}", ExitCodes.CONFIG_VALIDATION_ERROR)
        except Exception as e:
            exit_with_error(f"Failed to show configuration: {e}", ExitCodes.RCON_COMMAND_EXECUTION_FAILED)
    
    @staticmethod
    def update_config(args) -> None:
        """Update enterprise configuration."""
        try:
            config_manager = get_config_manager()
            
            # Parse value based on type
            value = args.value
            if value.lower() in ('true', 'false'):
                value = value.lower() == 'true'
            elif value.isdigit():
                value = int(value)
            elif value.startswith('[') and value.endswith(']'):
                # Simple list parsing
                value = [item.strip().strip('"\'') for item in value[1:-1].split(',') if item.strip()]
            
            config_manager.update_config({args.field: value})
            print(f"Updated {args.field} = {value}")
            
        except ConfigValidationError as e:
            exit_with_error(f"Configuration error: {e}", ExitCodes.CONFIG_VALIDATION_ERROR)
        except Exception as e:
            exit_with_error(f"Failed to update configuration: {e}", ExitCodes.RCON_COMMAND_EXECUTION_FAILED)
    
    @staticmethod
    def health_check(args) -> None:
        """Perform system health check."""
        try:
            health_checker = get_health_checker()
            health = health_checker.check_system_health()
            
            print("System Health Check")
            print("=" * 50)
            print(f"Overall Status: {health['status'].upper()}")
            print(f"Timestamp: {health['timestamp']}")
            
            if 'failed_checks' in health:
                print(f"Failed Checks: {', '.join(health['failed_checks'])}")
            
            print("\nDetailed Results:")
            for check_name, result in health.get('checks', {}).items():
                status = result.get('status', 'unknown').upper()
                print(f"  {check_name}: {status}")
                
                # Show additional details for some checks
                if check_name == 'disk_space' and 'free_gb' in result:
                    print(f"    Free: {result['free_gb']} GB ({result['free_percent']}%)")
                elif check_name == 'memory' and 'used_percent' in result:
                    print(f"    Used: {result['used_percent']}% ({result['available_mb']} MB available)")
                
                if result.get('error'):
                    print(f"    Error: {result['error']}")
            
            # Exit with appropriate code
            if health['status'] == 'unhealthy':
                sys.exit(ExitCodes.HEALTH_CHECK_FAILED)
            elif health['status'] == 'error':
                sys.exit(ExitCodes.RCON_COMMAND_EXECUTION_FAILED)
                
        except HealthCheckError as e:
            exit_with_error(f"Health check failed: {e}", ExitCodes.HEALTH_CHECK_FAILED)
        except Exception as e:
            exit_with_error(f"Health check error: {e}", ExitCodes.RCON_COMMAND_EXECUTION_FAILED)
    
    @staticmethod
    def collect_metrics(args) -> None:
        """Collect and display system metrics."""
        try:
            metrics_collector = get_metrics_collector()
            metrics = metrics_collector.collect_metrics()
            
            print("System Metrics")
            print("=" * 50)
            print(json.dumps(metrics, indent=2))
            
        except Exception as e:
            exit_with_error(f"Failed to collect metrics: {e}", ExitCodes.RCON_COMMAND_EXECUTION_FAILED)
    
    @staticmethod
    def log_audit_event(args) -> None:
        """Log an audit event."""
        try:
            audit_logger = get_audit_logger()
            
            # Parse details JSON
            try:
                details = json.loads(args.details)
            except json.JSONDecodeError as e:
                exit_with_error(f"Invalid JSON in details: {e}", ExitCodes.CONFIG_VALIDATION_ERROR)
            
            audit_logger.log_event(args.type, details)
            print(f"Logged audit event: {args.type}")
            
        except Exception as e:
            exit_with_error(f"Failed to log audit event: {e}", ExitCodes.RCON_COMMAND_EXECUTION_FAILED)
    
    @staticmethod
    def check_ip_access(args) -> None:
        """Check if IP has RCON access."""
        try:
            security_manager = get_security_manager()
            
            # Check access
            has_access = security_manager.check_rcon_access(args.ip)
            rate_limit_ok = security_manager.check_rate_limit(args.ip)
            
            print(f"Security Check for IP: {args.ip}")
            print("=" * 50)
            print(f"Access Allowed: {'YES' if has_access else 'NO'}")
            print(f"Rate Limit OK: {'YES' if rate_limit_ok else 'NO'}")
            print(f"Overall Access: {'GRANTED' if has_access and rate_limit_ok else 'DENIED'}")
            
            if not (has_access and rate_limit_ok):
                sys.exit(ExitCodes.SECURITY_VIOLATION)
                
        except SecurityViolationError as e:
            exit_with_error(f"Security violation: {e}", ExitCodes.SECURITY_VIOLATION)
        except Exception as e:
            exit_with_error(f"Security check failed: {e}", ExitCodes.RCON_COMMAND_EXECUTION_FAILED)


def create_parser() -> argparse.ArgumentParser:
    """Create the main argument parser."""
    parser = argparse.ArgumentParser(
        prog='asa-ctrl',
        description='ARK: Survival Ascended Server Control Tool with Enterprise Features'
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Add command parsers
    RconCommand.add_parser(subparsers)
    ModsCommand.add_parser(subparsers)
    EnterpriseCommand.add_parser(subparsers)

    # Hidden helper replacing external bash wrapper to output mods string
    hidden = subparsers.add_parser('mods-string', help=argparse.SUPPRESS)
    hidden.set_defaults(func=ModsCommand.print_mods_string)
    
    return parser


def main(args: Optional[List[str]] = None) -> None:
    """
    Main entry point for the CLI.
    
    Args:
        args: Command line arguments (uses sys.argv if None)
    """
    # Configure logging early (idempotent)
    configure_logging()
    logger = get_logger(__name__)
    parser = create_parser()
    
    if args is None:
        args = sys.argv[1:]
    
    # If no arguments provided, show help
    if not args:
        parser.print_help()
        sys.exit(ExitCodes.OK)
    
    parsed_args = parser.parse_args(args)
    # Lazy debug output if user enabled verbose logging
    raw_params = os.environ.get('ASA_START_PARAMS')
    if raw_params and logger.isEnabledFor(10):  # DEBUG level
        logger.debug("Parsed start params: %s", parse_start_params(raw_params))
    
    # Execute the appropriate command
    if hasattr(parsed_args, 'func'):
        parsed_args.func(parsed_args)
    else:
        parser.print_help()
        sys.exit(ExitCodes.OK)


if __name__ == '__main__':
    main()
