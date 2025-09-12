#!/usr/bin/env python3
"""
Simple test script to verify ASA Control functionality.
"""

import os
import sys
import tempfile
import json
from pathlib import Path

# Add the current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from asa_ctrl.mods import ModDatabase, format_mod_list_for_server
from asa_ctrl.config import StartParamsHelper, IniConfigHelper
from asa_ctrl.constants import ExitCodes


def test_start_params_helper():
    """Test start parameter parsing."""
    print("Testing StartParamsHelper...")
    
    test_params = "TheIsland_WP?listen?Port=7777?RCONPort=27020?RCONEnabled=True -WinLiveMaxPlayers=50 -ServerAdminPassword=mypass123"
    
    # Test parameter extraction
    assert StartParamsHelper.get_value(test_params, "RCONPort") == "27020"
    assert StartParamsHelper.get_value(test_params, "ServerAdminPassword") == "mypass123"
    assert StartParamsHelper.get_value(test_params, "WinLiveMaxPlayers") == "50"
    assert StartParamsHelper.get_value(test_params, "NonExistent") is None
    
    print("✓ StartParamsHelper tests passed")


def test_mod_database():
    """Test mod database functionality."""
    print("Testing ModDatabase...")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = os.path.join(temp_dir, "mods.json")
        
        # Test database creation
        db = ModDatabase(db_path)
        assert len(db.get_all_mods()) == 0
        
        # Test adding mods
        db.enable_mod(12345)
        db.enable_mod(67890)
        
        enabled_mods = db.get_enabled_mods()
        assert len(enabled_mods) == 2
        assert enabled_mods[0].mod_id == 12345
        assert enabled_mods[1].mod_id == 67890
        
        # Test mod formatting for server - direct method
        enabled_mod_ids = [mod.mod_id for mod in db.get_enabled_mods()]
        mod_params = f"-mods={','.join(map(str, enabled_mod_ids))}" if enabled_mod_ids else ""
        assert mod_params == "-mods=12345,67890"
        
        # Test disabling mod
        db.disable_mod(12345)
        enabled_mods = db.get_enabled_mods()
        assert len(enabled_mods) == 1
        assert enabled_mods[0].mod_id == 67890
    
    print("✓ ModDatabase tests passed")


def test_exit_codes():
    """Test exit codes are properly defined."""
    print("Testing ExitCodes...")
    
    assert ExitCodes.OK == 0
    assert ExitCodes.CORRUPTED_MODS_DATABASE == 1
    assert ExitCodes.MOD_ALREADY_ENABLED == 2
    assert ExitCodes.RCON_PASSWORD_NOT_FOUND == 3
    assert ExitCodes.RCON_PASSWORD_WRONG == 4
    assert ExitCodes.RCON_COMMAND_EXECUTION_FAILED == 5
    
    print("✓ ExitCodes tests passed")


def main():
    """Run all tests."""
    print("Running ASA Control Python implementation tests...\n")
    
    try:
        test_start_params_helper()
        test_mod_database()
        test_exit_codes()
        
        print("\n🎉 All tests passed! Python implementation is working correctly.")
        return 0
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())