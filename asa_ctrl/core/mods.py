"""
Mod management system for ASA Control.

Handles mod database operations including:
* Enabling/disabling mods
* Listing mods
* Persisting mod data to a JSON file
"""

import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import List, Dict, Any, Optional
from collections.abc import Mapping
from dataclasses import dataclass, asdict
from threading import RLock

from asa_ctrl.common.logging_config import get_logger

from asa_ctrl.common.config import AsaSettings
from asa_ctrl.common.constants import MOD_DATABASE_PATH
from asa_ctrl.common.errors import ModAlreadyEnabledError, CorruptedModsDatabaseError


@dataclass
class ModRecord:
    """Represents a mod record in the database."""

    mod_id: int
    name: str = "unknown"
    enabled: bool = False
    scanned: bool = False

    def to_dict(self) -> Dict[str, Any]:  # Backward compatibility
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ModRecord':
        return cls(
            mod_id=int(data['mod_id']),
            name=data.get('name', 'unknown'),
            enabled=bool(data.get('enabled', False)),
            scanned=bool(data.get('scanned', False)),
        )


class ModDatabase:
    """Manages the mod database for the ASA server."""

    def __init__(self, database_path: str = MOD_DATABASE_PATH):
        """
        Initialize the mod database.
        
        Args:
            database_path: Path to the mod database JSON file
        """
        self.database_path = Path(database_path)
        self.mods: List[ModRecord] = []
        self._lock = RLock()
        self._log = get_logger(__name__)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._file_lock():
            self._ensure_database_exists()
            self._load_database()
    
    @staticmethod
    def from_settings(settings: Optional[AsaSettings] = None) -> 'ModDatabase':
        """Create a mod database instance from settings."""
        settings = settings or AsaSettings()
        desired_path = settings.mod_database_path() or MOD_DATABASE_PATH
        return ModDatabase(desired_path)
    
    def _ensure_database_exists(self) -> None:
        """Ensure the database file exists, create if it doesn't."""
        if not self.database_path.exists():
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            self._write_database()
            self._log.debug("Created new mods database at %s", self.database_path)

    @contextmanager
    def _file_lock(self):
        # Lock a stable sibling: replacing mods.json must not replace the inode
        # that other processes are waiting on. Never unlink the lock file.
        with self.database_path.with_name(self.database_path.name + ".lock").open("a+b") as lock_file:
            if os.name == "nt":
                import msvcrt

                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl

                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if os.name == "nt":
                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    @contextmanager
    def _transaction(self):
        with self._lock, self._file_lock():
            # Another CLI process may have changed the database since this
            # instance was constructed. Reload under the same write lock.
            self._load_database()
            yield
    
    def _load_database(self) -> None:
        """Load the mod database from the JSON file."""
        try:
            with open(self.database_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if not isinstance(data, list):
                raise CorruptedModsDatabaseError(
                    "mods.json must contain a JSON array of mod objects."
                )
            mods: List[ModRecord] = []
            for index, mod_data in enumerate(data):
                if not isinstance(mod_data, Mapping):
                    raise CorruptedModsDatabaseError(
                        f"mods.json entry at index {index} must be a JSON object."
                    )
                try:
                    mods.append(ModRecord.from_dict(dict(mod_data)))
                except (TypeError, KeyError, ValueError) as e:
                    raise CorruptedModsDatabaseError(
                        f"mods.json entry at index {index} is invalid: {e}."
                    ) from e
            self.mods = mods
        except (json.JSONDecodeError, UnicodeError) as e:
            raise CorruptedModsDatabaseError(
                "mods.json file is corrupted and cannot be parsed: %s. "
                "Restore a known-good backup or repair the file before starting the server." % e
            ) from e
        self._log.debug("Loaded %d mods", len(self.mods))
    
    def _write_database(self) -> None:
        """Replace the database only after its complete contents reach disk."""
        data = [mod.to_dict() for mod in self.mods]
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.database_path.parent,
                prefix=self.database_path.name + ".", suffix=".tmp", delete=False,
            ) as f:
                temporary_path = Path(f.name)
                json.dump(data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temporary_path, self.database_path)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
        self._log.debug("Persisted %d mods", len(self.mods))
    
    def enable_mod(self, mod_id: int) -> None:
        """
        Enable a mod by ID.
        
        Args:
            mod_id: The mod ID to enable
            
        Raises:
            ModAlreadyEnabledError: If the mod is already enabled
        """
        # Check if mod already exists
        with self._transaction():
            for mod in self.mods:
                if mod.mod_id == mod_id:
                    if mod.enabled:
                        raise ModAlreadyEnabledError(f"Mod {mod_id} is already enabled")
                    mod.enabled = True
                    self._write_database()
                    self._log.info("Enabled existing mod %s", mod_id)
                    return
            new_mod = ModRecord(mod_id=mod_id, enabled=True)
            self.mods.append(new_mod)
            self._write_database()
            self._log.info("Added and enabled new mod %s", mod_id)
    
    def disable_mod(self, mod_id: int) -> bool:
        """
        Disable a mod by ID.
        
        Args:
            mod_id: The mod ID to disable
            
        Returns:
            True if mod was found and disabled, False otherwise
        """
        with self._transaction():
            for mod in self.mods:
                if mod.mod_id == mod_id:
                    if mod.enabled:
                        mod.enabled = False
                        self._write_database()
                        self._log.info("Disabled mod %s", mod_id)
                    else:
                        self._log.debug("Mod %s already disabled", mod_id)
                    return True
            return False
    
    def get_enabled_mods(self) -> List[ModRecord]:
        """Get a list of all enabled mods."""
        with self._transaction():
            return [mod for mod in self.mods if mod.enabled]
    
    def get_all_mods(self) -> List[ModRecord]:
        """Get a list of all mods in the database."""
        with self._transaction():
            return list(self.mods)
    
    def mod_exists(self, mod_id: int) -> bool:
        """Check if a mod exists in the database."""
        with self._transaction():
            return any(mod.mod_id == mod_id for mod in self.mods)
    
    def is_mod_enabled(self, mod_id: int) -> bool:
        """Check if a specific mod is enabled."""
        with self._transaction():
            for mod in self.mods:
                if mod.mod_id == mod_id:
                    return mod.enabled
            return False

    def get_mod(self, mod_id: int) -> Optional[ModRecord]:
        with self._transaction():
            for mod in self.mods:
                if mod.mod_id == mod_id:
                    return mod
            return None

    def remove_mod(self, mod_id: int) -> bool:
        with self._transaction():
            before = len(self.mods)
            self.mods = [m for m in self.mods if m.mod_id != mod_id]
            if len(self.mods) != before:
                self._write_database()
                self._log.info("Removed mod %s", mod_id)
                return True
            return False


def get_enabled_mod_ids(settings: Optional[AsaSettings] = None) -> List[int]:
    """
    Get a list of enabled mod IDs (convenience function).
    
    Returns:
        List of enabled mod IDs
    """
    db = ModDatabase.from_settings(settings)
    return [mod.mod_id for mod in db.get_enabled_mods()]


def format_mod_list_for_server(settings: Optional[AsaSettings] = None) -> str:
    """
    Format the enabled mods list for use in server start parameters.
    
    Returns:
        Formatted mod list string for server parameters
    """
    mod_ids = get_enabled_mod_ids(settings)
    if not mod_ids:
        return ""
    
    return f"-mods={','.join(map(str, mod_ids))}"
