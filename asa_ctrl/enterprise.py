"""
Enterprise features for ASA Control.

Provides enterprise-grade functionality including:
* Configuration validation and management
* Security and authentication
* Health checks and monitoring
* Audit logging
* Backup and recovery
"""

import json
import os
import time
import hashlib
import socket
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional, Any, Union
from datetime import datetime, timezone
from threading import RLock

from .constants import CONFIG_DIR, AUDIT_LOG_PATH, METRICS_PATH, BACKUP_DIR
from .logging_config import get_logger
from .errors import AsaCtrlError


class ConfigValidationError(AsaCtrlError):
    """Configuration validation error."""
    pass


class SecurityViolationError(AsaCtrlError):
    """Security violation error."""
    pass


class HealthCheckError(AsaCtrlError):
    """Health check error."""
    pass


@dataclass
class ConfigSchema:
    """Enterprise configuration schema."""
    # Server configuration
    server_name: str = "ASA Enterprise Server"
    max_players: int = 50
    admin_password: str = ""
    
    # Security settings
    enable_rcon_rate_limiting: bool = True
    max_rcon_requests_per_minute: int = 60
    allowed_rcon_ips: List[str] = None
    enable_audit_logging: bool = True
    
    # Monitoring settings  
    health_check_enabled: bool = True
    health_check_interval: int = 60
    metrics_collection_enabled: bool = True
    alert_on_high_memory: bool = True
    memory_threshold_mb: int = 10240
    
    # Backup settings
    auto_backup_enabled: bool = True
    backup_interval_hours: int = 6
    backup_retention_days: int = 30
    
    # API settings
    api_enabled: bool = False
    api_port: int = 8080
    api_auth_token: str = ""
    
    def __post_init__(self):
        if self.allowed_rcon_ips is None:
            self.allowed_rcon_ips = ["127.0.0.1", "::1"]


class EnterpriseConfigManager:
    """Manages enterprise configuration with validation and persistence."""
    
    def __init__(self, config_dir: str = CONFIG_DIR):
        self.config_dir = Path(config_dir)
        self.config_file = self.config_dir / "enterprise.json"
        self._config: Optional[ConfigSchema] = None
        self._lock = RLock()
        self._log = get_logger(__name__)
        self._ensure_config_dir()
        
    def _ensure_config_dir(self) -> None:
        """Ensure configuration directory exists."""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        
    def load_config(self) -> ConfigSchema:
        """Load and validate configuration."""
        with self._lock:
            if self._config is None:
                if self.config_file.exists():
                    try:
                        with open(self.config_file, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                        self._config = ConfigSchema(**data)
                        self._log.info("Loaded enterprise configuration from %s", self.config_file)
                    except Exception as e:
                        self._log.error("Failed to load config: %s", e)
                        raise ConfigValidationError(f"Invalid configuration: {e}")
                else:
                    self._config = ConfigSchema()
                    self.save_config()
                    self._log.info("Created default enterprise configuration")
            return self._config
    
    def save_config(self) -> None:
        """Save configuration to file."""
        with self._lock:
            if self._config is None:
                raise ConfigValidationError("No configuration to save")
            
            try:
                with open(self.config_file, 'w', encoding='utf-8') as f:
                    json.dump(asdict(self._config), f, indent=2)
                self._log.info("Saved enterprise configuration to %s", self.config_file)
            except Exception as e:
                self._log.error("Failed to save config: %s", e)
                raise ConfigValidationError(f"Failed to save configuration: {e}")
    
    def update_config(self, updates: Dict[str, Any]) -> None:
        """Update configuration with validation."""
        config = self.load_config()
        
        # Validate updates
        valid_fields = set(asdict(config).keys())
        invalid_fields = set(updates.keys()) - valid_fields
        if invalid_fields:
            raise ConfigValidationError(f"Invalid configuration fields: {invalid_fields}")
        
        # Apply updates
        for key, value in updates.items():
            if hasattr(config, key):
                setattr(config, key, value)
        
        self._config = config
        self.save_config()
        
        # Log configuration change
        AuditLogger().log_event("config_updated", {
            "fields": list(updates.keys()),
            "user": os.environ.get("USER", "system")
        })
    
    def get_config(self) -> ConfigSchema:
        """Get current configuration."""
        return self.load_config()


class SecurityManager:
    """Manages enterprise security features."""
    
    def __init__(self, config_manager: EnterpriseConfigManager):
        self.config_manager = config_manager
        self._rate_limits: Dict[str, List[float]] = {}
        self._lock = RLock()
        self._log = get_logger(__name__)
    
    def check_rcon_access(self, client_ip: str) -> bool:
        """Check if IP is allowed for RCON access."""
        config = self.config_manager.get_config()
        
        if client_ip not in config.allowed_rcon_ips:
            self._log.warning("RCON access denied for IP: %s", client_ip)
            AuditLogger().log_security_event("rcon_access_denied", {
                "client_ip": client_ip,
                "allowed_ips": config.allowed_rcon_ips
            })
            return False
        
        return True
    
    def check_rate_limit(self, client_ip: str) -> bool:
        """Check RCON rate limiting."""
        config = self.config_manager.get_config()
        
        if not config.enable_rcon_rate_limiting:
            return True
        
        with self._lock:
            now = time.time()
            minute_ago = now - 60
            
            # Initialize or clean old entries
            if client_ip not in self._rate_limits:
                self._rate_limits[client_ip] = []
            
            # Remove old entries
            self._rate_limits[client_ip] = [
                timestamp for timestamp in self._rate_limits[client_ip]
                if timestamp > minute_ago
            ]
            
            # Check if under limit
            if len(self._rate_limits[client_ip]) >= config.max_rcon_requests_per_minute:
                self._log.warning("RCON rate limit exceeded for IP: %s", client_ip)
                AuditLogger().log_security_event("rcon_rate_limit_exceeded", {
                    "client_ip": client_ip,
                    "requests_in_minute": len(self._rate_limits[client_ip])
                })
                return False
            
            # Add current request
            self._rate_limits[client_ip].append(now)
            return True
    
    def validate_input(self, command: str) -> bool:
        """Validate RCON command input for security."""
        # Basic security checks
        dangerous_patterns = [
            ';', '&&', '||', '`', '$(',  # Command injection
            '../', '..\\',  # Path traversal
            '<script', '</script>',  # XSS (if command goes to web interface)
        ]
        
        command_lower = command.lower()
        for pattern in dangerous_patterns:
            if pattern in command_lower:
                self._log.warning("Potentially dangerous command blocked: %s", command)
                AuditLogger().log_security_event("dangerous_command_blocked", {
                    "command": command,
                    "pattern": pattern
                })
                return False
        
        return True


class AuditLogger:
    """Enterprise audit logging system."""
    
    def __init__(self, log_path: str = AUDIT_LOG_PATH):
        self.log_path = Path(log_path)
        self._lock = RLock()
        self._log = get_logger(__name__)
        self._ensure_log_dir()
    
    def _ensure_log_dir(self) -> None:
        """Ensure audit log directory exists."""
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
    
    def log_event(self, event_type: str, details: Dict[str, Any]) -> None:
        """Log an audit event."""
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "details": details,
            "hostname": socket.gethostname(),
            "pid": os.getpid()
        }
        
        with self._lock:
            try:
                with open(self.log_path, 'a', encoding='utf-8') as f:
                    f.write(json.dumps(event) + '\n')
            except Exception as e:
                self._log.error("Failed to write audit log: %s", e)
    
    def log_security_event(self, event_type: str, details: Dict[str, Any]) -> None:
        """Log a security-related event."""
        details["security_event"] = True
        self.log_event(f"security_{event_type}", details)
    
    def log_admin_action(self, action: str, details: Dict[str, Any]) -> None:
        """Log an administrative action."""
        details["admin_action"] = True
        self.log_event(f"admin_{action}", details)


class HealthChecker:
    """Enterprise health checking system."""
    
    def __init__(self, config_manager: EnterpriseConfigManager):
        self.config_manager = config_manager
        self._log = get_logger(__name__)
    
    def check_system_health(self) -> Dict[str, Any]:
        """Perform comprehensive system health check."""
        health = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "healthy",
            "checks": {}
        }
        
        try:
            # Check disk space
            health["checks"]["disk_space"] = self._check_disk_space()
            
            # Check memory usage
            health["checks"]["memory"] = self._check_memory()
            
            # Check process health
            health["checks"]["processes"] = self._check_processes()
            
            # Check configuration
            health["checks"]["configuration"] = self._check_configuration()
            
            # Overall status
            failed_checks = [
                check for check, result in health["checks"].items()
                if result.get("status") != "ok"
            ]
            
            if failed_checks:
                health["status"] = "degraded" if len(failed_checks) < 2 else "unhealthy"
                health["failed_checks"] = failed_checks
                
        except Exception as e:
            health["status"] = "error"
            health["error"] = str(e)
            self._log.error("Health check failed: %s", e)
        
        return health
    
    def _check_disk_space(self) -> Dict[str, Any]:
        """Check available disk space."""
        try:
            import shutil
            total, used, free = shutil.disk_usage("/")
            free_percent = (free / total) * 100
            
            return {
                "status": "ok" if free_percent > 10 else "warning",
                "free_gb": round(free / (1024**3), 2),
                "free_percent": round(free_percent, 1),
                "total_gb": round(total / (1024**3), 2)
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}
    
    def _check_memory(self) -> Dict[str, Any]:
        """Check memory usage."""
        try:
            # Basic memory check using /proc/meminfo
            with open("/proc/meminfo", "r") as f:
                meminfo = f.read()
            
            mem_total = None
            mem_available = None
            
            for line in meminfo.splitlines():
                if line.startswith("MemTotal:"):
                    mem_total = int(line.split()[1]) * 1024  # Convert from KB to bytes
                elif line.startswith("MemAvailable:"):
                    mem_available = int(line.split()[1]) * 1024
            
            if mem_total and mem_available:
                used_percent = ((mem_total - mem_available) / mem_total) * 100
                config = self.config_manager.get_config()
                
                return {
                    "status": "ok" if used_percent < 90 else "warning",
                    "used_percent": round(used_percent, 1),
                    "available_mb": round(mem_available / (1024**2), 0),
                    "total_mb": round(mem_total / (1024**2), 0),
                    "alert_threshold": config.memory_threshold_mb
                }
            else:
                return {"status": "error", "error": "Could not parse memory info"}
                
        except Exception as e:
            return {"status": "error", "error": str(e)}
    
    def _check_processes(self) -> Dict[str, Any]:
        """Check critical processes."""
        try:
            # Check if ASA server process is running (basic check)
            pid_file = Path("/home/gameserver/server-files/asa.pid")
            if pid_file.exists():
                try:
                    with open(pid_file, "r") as f:
                        pid = int(f.read().strip())
                    
                    # Check if process is still running
                    os.kill(pid, 0)  # Doesn't actually kill, just checks if process exists
                    return {"status": "ok", "server_pid": pid, "server_running": True}
                except (ProcessLookupError, ValueError):
                    return {"status": "warning", "server_running": False, "note": "PID file exists but process not found"}
            else:
                return {"status": "warning", "server_running": False, "note": "No PID file found"}
                
        except Exception as e:
            return {"status": "error", "error": str(e)}
    
    def _check_configuration(self) -> Dict[str, Any]:
        """Check configuration validity."""
        try:
            config = self.config_manager.get_config()
            return {
                "status": "ok",
                "config_loaded": True,
                "health_check_enabled": config.health_check_enabled
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}


class MetricsCollector:
    """Enterprise metrics collection system."""
    
    def __init__(self, metrics_path: str = METRICS_PATH):
        self.metrics_path = Path(metrics_path)
        self._log = get_logger(__name__)
        self._ensure_metrics_dir()
    
    def _ensure_metrics_dir(self) -> None:
        """Ensure metrics directory exists."""
        self.metrics_path.mkdir(parents=True, exist_ok=True)
    
    def collect_metrics(self) -> Dict[str, Any]:
        """Collect system and application metrics."""
        metrics = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "hostname": socket.gethostname(),
            "system": self._collect_system_metrics(),
            "application": self._collect_app_metrics()
        }
        
        # Save metrics to file
        self._save_metrics(metrics)
        
        return metrics
    
    def _collect_system_metrics(self) -> Dict[str, Any]:
        """Collect system-level metrics."""
        metrics = {}
        
        try:
            # CPU usage (basic)
            with open("/proc/loadavg", "r") as f:
                load_avg = f.read().strip().split()
                metrics["load_avg"] = {
                    "1min": float(load_avg[0]),
                    "5min": float(load_avg[1]),
                    "15min": float(load_avg[2])
                }
        except Exception as e:
            self._log.warning("Could not collect load average: %s", e)
        
        try:
            # Memory metrics
            with open("/proc/meminfo", "r") as f:
                meminfo = f.read()
            
            for line in meminfo.splitlines():
                if line.startswith("MemTotal:"):
                    metrics["memory_total_kb"] = int(line.split()[1])
                elif line.startswith("MemAvailable:"):
                    metrics["memory_available_kb"] = int(line.split()[1])
                elif line.startswith("MemFree:"):
                    metrics["memory_free_kb"] = int(line.split()[1])
        except Exception as e:
            self._log.warning("Could not collect memory metrics: %s", e)
        
        return metrics
    
    def _collect_app_metrics(self) -> Dict[str, Any]:
        """Collect application-specific metrics."""
        metrics = {}
        
        try:
            # Check if mod database exists and count mods
            from .mods import ModDatabase
            db = ModDatabase.get_instance()
            enabled_mods = db.get_enabled_mods()
            metrics["enabled_mods_count"] = len(enabled_mods)
            metrics["enabled_mod_ids"] = [mod.mod_id for mod in enabled_mods]
        except Exception as e:
            self._log.warning("Could not collect mod metrics: %s", e)
        
        return metrics
    
    def _save_metrics(self, metrics: Dict[str, Any]) -> None:
        """Save metrics to file."""
        try:
            timestamp = datetime.now().strftime("%Y%m%d")
            metrics_file = self.metrics_path / f"metrics_{timestamp}.jsonl"
            
            with open(metrics_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(metrics) + '\n')
        except Exception as e:
            self._log.error("Failed to save metrics: %s", e)


# Initialize enterprise components  
_config_manager = None
_security_manager = None
_audit_logger = None
_health_checker = None
_metrics_collector = None


def get_config_manager() -> EnterpriseConfigManager:
    """Get the global configuration manager instance."""
    global _config_manager
    if _config_manager is None:
        _config_manager = EnterpriseConfigManager()
    return _config_manager


def get_security_manager() -> SecurityManager:
    """Get the global security manager instance."""
    global _security_manager
    if _security_manager is None:
        _security_manager = SecurityManager(get_config_manager())
    return _security_manager


def get_audit_logger() -> AuditLogger:
    """Get the global audit logger instance."""
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger()
    return _audit_logger


def get_health_checker() -> HealthChecker:
    """Get the global health checker instance."""
    global _health_checker
    if _health_checker is None:
        _health_checker = HealthChecker(get_config_manager())
    return _health_checker


def get_metrics_collector() -> MetricsCollector:
    """Get the global metrics collector instance."""
    global _metrics_collector
    if _metrics_collector is None:
        _metrics_collector = MetricsCollector()
    return _metrics_collector