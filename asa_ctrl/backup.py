"""
Enterprise backup and recovery system for ASA Control.

Provides automated backup capabilities including:
* Configuration backups
* Save game backups  
* Mod database backups
* Audit log archiving
* Automated cleanup of old backups
"""

import os
import json
import tarfile
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional
import threading
import time

from .constants import BACKUP_DIR
from .enterprise import get_config_manager, get_audit_logger
from .logging_config import get_logger
from .errors import AsaCtrlError


class BackupError(AsaCtrlError):
    """Backup operation error."""
    pass


class BackupManager:
    """Manages enterprise backup operations."""
    
    def __init__(self, backup_dir: str = BACKUP_DIR):
        self.backup_dir = Path(backup_dir)
        self._log = get_logger(__name__)
        self._ensure_backup_dir()
        self._background_thread: Optional[threading.Thread] = None
        self._stop_background = False
    
    def _ensure_backup_dir(self) -> None:
        """Ensure backup directory exists."""
        self.backup_dir.mkdir(parents=True, exist_ok=True)
    
    def create_backup(self, backup_type: str = "full", description: str = "") -> str:
        """Create a backup of specified type."""
        timestamp = datetime.now(timezone.utc)
        backup_name = f"{backup_type}_{timestamp.strftime('%Y%m%d_%H%M%S')}"
        backup_path = self.backup_dir / f"{backup_name}.tar.gz"
        
        self._log.info("Creating %s backup: %s", backup_type, backup_name)
        
        try:
            with tarfile.open(backup_path, 'w:gz') as tar:
                if backup_type in ('full', 'config'):
                    self._add_config_to_backup(tar)
                
                if backup_type in ('full', 'saves'):
                    self._add_saves_to_backup(tar)
                
                if backup_type in ('full', 'mods'):
                    self._add_mods_to_backup(tar)
                
                if backup_type in ('full', 'logs'):
                    self._add_logs_to_backup(tar)
            
            # Create backup metadata
            metadata = {
                "backup_name": backup_name,
                "backup_type": backup_type,
                "description": description,
                "created_at": timestamp.isoformat(),
                "size_bytes": backup_path.stat().st_size,
                "files_included": self._get_backup_contents(backup_type)
            }
            
            metadata_path = self.backup_dir / f"{backup_name}.json"
            with open(metadata_path, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2)
            
            # Log the backup creation
            audit_logger = get_audit_logger()
            audit_logger.log_admin_action("backup_created", {
                "backup_name": backup_name,
                "backup_type": backup_type,
                "size_mb": round(metadata["size_bytes"] / (1024 * 1024), 2),
                "description": description
            })
            
            self._log.info("Backup created successfully: %s (%.2f MB)", 
                          backup_name, metadata["size_bytes"] / (1024 * 1024))
            
            return backup_name
            
        except Exception as e:
            self._log.error("Failed to create backup: %s", e)
            # Clean up partial backup
            if backup_path.exists():
                backup_path.unlink()
            raise BackupError(f"Backup creation failed: {e}")
    
    def _add_config_to_backup(self, tar: tarfile.TarFile) -> None:
        """Add configuration files to backup."""
        config_manager = get_config_manager()
        
        # Add enterprise config
        if config_manager.config_file.exists():
            tar.add(config_manager.config_file, arcname="config/enterprise.json")
        
        # Add game config files if they exist
        game_user_settings = os.environ.get('ASA_GAME_USER_SETTINGS_PATH', 
                                           '/home/gameserver/server-files/ShooterGame/Saved/Config/WindowsServer/GameUserSettings.ini')
        game_ini = os.environ.get('ASA_GAME_INI_PATH', 
                                 '/home/gameserver/server-files/ShooterGame/Saved/Config/WindowsServer/Game.ini')
        
        game_configs = [game_user_settings, game_ini]
        
        for config_path in game_configs:
            path = Path(config_path)
            if path.exists():
                tar.add(path, arcname=f"config/{path.name}")
    
    def _add_saves_to_backup(self, tar: tarfile.TarFile) -> None:
        """Add save game files to backup."""
        saves_dir = Path(os.environ.get('ASA_SAVES_DIR', '/home/gameserver/server-files/ShooterGame/Saved/SavedArks'))
        if saves_dir.exists():
            tar.add(saves_dir, arcname="saves")
    
    def _add_mods_to_backup(self, tar: tarfile.TarFile) -> None:
        """Add mod database to backup."""
        mods_db = Path(os.environ.get('ASA_MOD_DATABASE_PATH', '/home/gameserver/server-files/mods.json'))
        if mods_db.exists():
            tar.add(mods_db, arcname="mods/mods.json")
    
    def _add_logs_to_backup(self, tar: tarfile.TarFile) -> None:
        """Add log files to backup."""
        # Add audit logs
        audit_logger = get_audit_logger()
        if audit_logger.log_path.exists():
            tar.add(audit_logger.log_path, arcname="logs/audit.log")
        
        # Add game logs
        log_dir = Path(os.environ.get('ASA_GAME_LOGS_DIR', '/home/gameserver/server-files/ShooterGame/Saved/Logs'))
        if log_dir.exists():
            tar.add(log_dir, arcname="logs/game")
    
    def _get_backup_contents(self, backup_type: str) -> List[str]:
        """Get list of files included in backup type."""
        contents = []
        
        if backup_type in ('full', 'config'):
            contents.extend(['enterprise.json', 'GameUserSettings.ini', 'Game.ini'])
        
        if backup_type in ('full', 'saves'):
            contents.append('SavedArks/')
        
        if backup_type in ('full', 'mods'):
            contents.append('mods.json')
        
        if backup_type in ('full', 'logs'):
            contents.extend(['audit.log', 'game_logs/'])
        
        return contents
    
    def list_backups(self) -> List[Dict[str, Any]]:
        """List all available backups."""
        backups = []
        
        for backup_file in self.backup_dir.glob("*.tar.gz"):
            # Get the base name without .tar.gz and add .json
            base_name = backup_file.name[:-7]  # Remove .tar.gz
            metadata_file = backup_file.parent / f"{base_name}.json"
            
            if metadata_file.exists():
                try:
                    with open(metadata_file, 'r', encoding='utf-8') as f:
                        metadata = json.load(f)
                    backups.append(metadata)
                except Exception as e:
                    self._log.warning("Failed to read backup metadata for %s: %s", backup_file.name, e)
                    # Create basic metadata
                    stat = backup_file.stat()
                    backups.append({
                        "backup_name": base_name,
                        "backup_type": "unknown",
                        "description": "Metadata file missing or corrupted",
                        "created_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                        "size_bytes": stat.st_size,
                        "files_included": ["unknown"]
                    })
        
        # Sort by creation time (newest first)
        backups.sort(key=lambda x: x['created_at'], reverse=True)
        return backups
    
    def restore_backup(self, backup_name: str, restore_type: str = "config") -> None:
        """Restore from a backup."""
        backup_path = self.backup_dir / f"{backup_name}.tar.gz"
        
        if not backup_path.exists():
            raise BackupError(f"Backup not found: {backup_name}")
        
        self._log.info("Restoring %s from backup: %s", restore_type, backup_name)
        
        try:
            with tarfile.open(backup_path, 'r:gz') as tar:
                if restore_type in ('config', 'all'):
                    self._restore_config_from_backup(tar)
                
                if restore_type in ('saves', 'all'):
                    self._restore_saves_from_backup(tar)
                
                if restore_type in ('mods', 'all'):
                    self._restore_mods_from_backup(tar)
            
            # Log the restore operation
            audit_logger = get_audit_logger()
            audit_logger.log_admin_action("backup_restored", {
                "backup_name": backup_name,
                "restore_type": restore_type,
                "user": os.environ.get("USER", "system")
            })
            
            self._log.info("Successfully restored %s from backup: %s", restore_type, backup_name)
            
        except Exception as e:
            self._log.error("Failed to restore backup: %s", e)
            raise BackupError(f"Backup restoration failed: {e}")
    
    def _restore_config_from_backup(self, tar: tarfile.TarFile) -> None:
        """Restore configuration files from backup."""
        # Extract to temp directory first
        import tempfile
        
        with tempfile.TemporaryDirectory() as temp_dir:
            # Extract config files
            for member in tar.getmembers():
                if member.name.startswith('config/'):
                    tar.extract(member, temp_dir)
            
            # Copy files to actual locations
            config_dir = Path(temp_dir) / "config"
            if config_dir.exists():
                for config_file in config_dir.iterdir():
                    if config_file.name == "enterprise.json":
                        # Restore enterprise config
                        config_manager = get_config_manager()
                        shutil.copy2(config_file, config_manager.config_file)
                    elif config_file.name in ("GameUserSettings.ini", "Game.ini"):
                        # Restore game configs
                        target_dir = Path("/home/gameserver/server-files/ShooterGame/Saved/Config/WindowsServer")
                        target_dir.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(config_file, target_dir / config_file.name)
    
    def _restore_saves_from_backup(self, tar: tarfile.TarFile) -> None:
        """Restore save game files from backup."""
        # Extract saves to temp directory first
        import tempfile
        
        with tempfile.TemporaryDirectory() as temp_dir:
            for member in tar.getmembers():
                if member.name.startswith('saves/'):
                    tar.extract(member, temp_dir)
            
            saves_source = Path(temp_dir) / "saves"
            if saves_source.exists():
                saves_target = Path("/home/gameserver/server-files/ShooterGame/Saved/SavedArks")
                
                # Backup existing saves first
                if saves_target.exists():
                    backup_existing = saves_target.parent / f"SavedArks_backup_{int(time.time())}"
                    shutil.move(str(saves_target), str(backup_existing))
                
                # Copy restored saves
                shutil.copytree(str(saves_source), str(saves_target))
    
    def _restore_mods_from_backup(self, tar: tarfile.TarFile) -> None:
        """Restore mod database from backup."""
        import tempfile
        
        with tempfile.TemporaryDirectory() as temp_dir:
            for member in tar.getmembers():
                if member.name.startswith('mods/'):
                    tar.extract(member, temp_dir)
            
            mods_source = Path(temp_dir) / "mods" / "mods.json"
            if mods_source.exists():
                mods_target = Path("/home/gameserver/server-files/mods.json")
                mods_target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(mods_source, mods_target)
    
    def delete_backup(self, backup_name: str) -> None:
        """Delete a backup."""
        backup_path = self.backup_dir / f"{backup_name}.tar.gz"
        metadata_path = self.backup_dir / f"{backup_name}.json"
        
        if not backup_path.exists():
            raise BackupError(f"Backup not found: {backup_name}")
        
        try:
            backup_path.unlink()
            if metadata_path.exists():
                metadata_path.unlink()
            
            # Log the deletion
            audit_logger = get_audit_logger()
            audit_logger.log_admin_action("backup_deleted", {
                "backup_name": backup_name,
                "user": os.environ.get("USER", "system")
            })
            
            self._log.info("Deleted backup: %s", backup_name)
            
        except Exception as e:
            self._log.error("Failed to delete backup: %s", e)
            raise BackupError(f"Backup deletion failed: {e}")
    
    def cleanup_old_backups(self) -> int:
        """Clean up old backups based on retention policy."""
        config_manager = get_config_manager()
        config = config_manager.get_config()
        
        if not config.auto_backup_enabled:
            return 0
        
        retention_days = config.backup_retention_days
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=retention_days)
        
        backups = self.list_backups()
        deleted_count = 0
        
        for backup in backups:
            created_at = datetime.fromisoformat(backup['created_at'])
            if created_at < cutoff_date:
                try:
                    self.delete_backup(backup['backup_name'])
                    deleted_count += 1
                except Exception as e:
                    self._log.warning("Failed to delete old backup %s: %s", backup['backup_name'], e)
        
        if deleted_count > 0:
            self._log.info("Cleaned up %d old backups (older than %d days)", deleted_count, retention_days)
        
        return deleted_count
    
    def start_background_backup(self) -> None:
        """Start background backup scheduler."""
        if self._background_thread and self._background_thread.is_alive():
            return
        
        config_manager = get_config_manager()
        config = config_manager.get_config()
        
        if not config.auto_backup_enabled:
            self._log.info("Automatic backups are disabled")
            return
        
        self._stop_background = False
        self._background_thread = threading.Thread(target=self._background_backup_loop, daemon=True)
        self._background_thread.start()
        
        self._log.info("Started background backup scheduler (interval: %d hours)", 
                      config.backup_interval_hours)
    
    def stop_background_backup(self) -> None:
        """Stop background backup scheduler."""
        self._stop_background = True
        if self._background_thread and self._background_thread.is_alive():
            self._background_thread.join(timeout=5)
    
    def _background_backup_loop(self) -> None:
        """Background backup loop."""
        config_manager = get_config_manager()
        
        while not self._stop_background:
            try:
                config = config_manager.get_config()
                interval_seconds = config.backup_interval_hours * 3600
                
                # Sleep in chunks to allow for stopping
                for _ in range(interval_seconds):
                    if self._stop_background:
                        return
                    time.sleep(1)
                
                # Create automatic backup
                if config.auto_backup_enabled:
                    backup_name = self.create_backup("full", "Automatic scheduled backup")
                    self._log.info("Automatic backup created: %s", backup_name)
                    
                    # Clean up old backups
                    deleted = self.cleanup_old_backups()
                    if deleted > 0:
                        self._log.info("Cleaned up %d old backups", deleted)
                
            except Exception as e:
                self._log.error("Background backup failed: %s", e)
                # Continue the loop even if backup fails


# Global backup manager instance
_backup_manager: Optional[BackupManager] = None


def get_backup_manager() -> BackupManager:
    """Get the global backup manager instance."""
    global _backup_manager
    if _backup_manager is None:
        _backup_manager = BackupManager()
    return _backup_manager