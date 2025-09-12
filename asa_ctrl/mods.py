"""
Mod management system for ASA Control.

Handles mod database operations including:
* Enabling/disabling mods
* Listing mods
* Persisting mod data to a JSON file
"""

import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict
from threading import RLock

from .logging_config import get_logger

from .constants import MOD_DATABASE_PATH
from .errors import ModAlreadyEnabledError, CorruptedModsDatabaseError


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
    
    _instance: Optional['ModDatabase'] = None
    
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
        self._ensure_database_exists()
        self._load_database()
    
    @classmethod
    def get_instance(cls) -> 'ModDatabase':
        """Get the singleton instance of the mod database."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def _ensure_database_exists(self) -> None:
        """Ensure the database file exists, create if it doesn't."""
        if not self.database_path.exists():
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            self._write_database()
            self._log.debug("Created new mods database at %s", self.database_path)
    
    def _load_database(self) -> None:
        """Load the mod database from the JSON file."""
        try:
            with open(self.database_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self.mods = [ModRecord.from_dict(mod_data) for mod_data in data]
        except json.JSONDecodeError as e:
            raise CorruptedModsDatabaseError(
                "mods.json file is corrupted and cannot be parsed: %s. Please delete this file manually. It can be found in the server files root directory." % e
            )
        except FileNotFoundError:
            self.mods = []
        self._log.debug("Loaded %d mods", len(self.mods))
    
    def _write_database(self) -> None:
        """Write the mod database to the JSON file."""
        data = [mod.to_dict() for mod in self.mods]
        with open(self.database_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
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
        with self._lock:
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
        with self._lock:
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
        return [mod for mod in self.mods if mod.enabled]
    
    def get_all_mods(self) -> List[ModRecord]:
        """Get a list of all mods in the database."""
        return list(self.mods)
    
    def mod_exists(self, mod_id: int) -> bool:
        """Check if a mod exists in the database."""
        return any(mod.mod_id == mod_id for mod in self.mods)
    
    def is_mod_enabled(self, mod_id: int) -> bool:
        """Check if a specific mod is enabled."""
        for mod in self.mods:
            if mod.mod_id == mod_id:
                return mod.enabled
        return False

    def get_mod(self, mod_id: int) -> Optional[ModRecord]:
        for mod in self.mods:
            if mod.mod_id == mod_id:
                return mod
        return None

    def remove_mod(self, mod_id: int) -> bool:
        with self._lock:
            before = len(self.mods)
            self.mods = [m for m in self.mods if m.mod_id != mod_id]
            if len(self.mods) != before:
                self._write_database()
                self._log.info("Removed mod %s", mod_id)
                return True
            return False


def get_enabled_mod_ids() -> List[int]:
    """
    Get a list of enabled mod IDs (convenience function).
    
    Returns:
        List of enabled mod IDs
    """
    db = ModDatabase.get_instance()
    return [mod.mod_id for mod in db.get_enabled_mods()]


def format_mod_list_for_server() -> str:
    """
    Format the enabled mods list for use in server start parameters.
    
    Returns:
        Formatted mod list string for server parameters
    """
    mod_ids = get_enabled_mod_ids()
    if not mod_ids:
        return ""
    
    return f"-mods={','.join(map(str, mod_ids))}"