#!/usr/bin/env python3
"""Test suite for asa_ctrl package.

Migrated from repository root to tests/ directory.
Run with: `py -m tests.test_asa_ctrl` or `py tests/test_asa_ctrl.py`.
"""

from __future__ import annotations

import os
import sys
import tempfile

# Set test environment before importing modules
os.environ.setdefault('ASA_MOD_DATABASE_PATH', '/tmp/test_mods.json')
os.environ.setdefault('ASA_GAME_USER_SETTINGS_PATH', '/tmp/test_game_settings.ini')
os.environ.setdefault('ASA_GAME_INI_PATH', '/tmp/test_game.ini')
os.environ.setdefault('ASA_CONFIG_DIR', '/tmp/test_config')
os.environ.setdefault('ASA_AUDIT_LOG_PATH', '/tmp/test_audit.log')
os.environ.setdefault('ASA_METRICS_PATH', '/tmp/test_metrics')
os.environ.setdefault('ASA_BACKUP_DIR', '/tmp/test_backups')

# Ensure project root is on sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from asa_ctrl.mods import ModDatabase, ModRecord  # noqa: E402
from asa_ctrl.config import StartParamsHelper, parse_start_params  # noqa: E402
from asa_ctrl.constants import ExitCodes  # noqa: E402
from asa_ctrl.cli import main as cli_main  # noqa: E402


def test_start_params_helper():
    """Test start parameter parsing."""
    print("Testing StartParamsHelper...")

    test_params = (
        "TheIsland_WP?listen?Port=7777?RCONPort=27020?RCONEnabled=True "
        "-WinLiveMaxPlayers=50 -ServerAdminPassword=mypass123"
    )

    assert StartParamsHelper.get_value(test_params, "RCONPort") == "27020"
    assert StartParamsHelper.get_value(test_params, "ServerAdminPassword") == "mypass123"
    assert StartParamsHelper.get_value(test_params, "WinLiveMaxPlayers") == "50"
    assert StartParamsHelper.get_value(test_params, "NonExistent") is None

    parsed = parse_start_params(test_params)
    assert parsed.get('_map') == 'TheIsland_WP'
    assert parsed.get('RCONPort') == '27020'
    assert parsed.get('WinLiveMaxPlayers') == '50'

    print("✓ StartParamsHelper tests passed")


def test_ini_config_helper_duplicate_keys():
    """Test that IniConfigHelper handles duplicate keys in INI files gracefully."""
    print("Testing IniConfigHelper with duplicate keys...")
    
    from asa_ctrl.config import IniConfigHelper
    
    # Create a test INI file with duplicate keys (similar to ARK GameUserSettings.ini)
    ini_content = """[/Script/ShooterGame.ShooterGameUserSettings]
LastJoinedSessionPerCategory=
LastJoinedSessionPerCategory=test_value
RCONPort=27020

[ServerSettings]
RCONPort=27020
ServerAdminPassword=testpass
"""
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.ini', delete=False) as f:
        f.write(ini_content)
        f.flush()
        
        try:
            # This should now work with the fix (strict=False)
            config = IniConfigHelper.parse_ini(f.name)
            assert config is not None, "Config should not be None"
            assert len(config.sections()) == 2, "Should have 2 sections"
            
            # Test that duplicate key uses the last value
            game_section = config['/Script/ShooterGame.ShooterGameUserSettings']
            assert game_section['LastJoinedSessionPerCategory'] == 'test_value', "Should use last duplicate value"
            assert game_section['RCONPort'] == '27020', "RCONPort should be accessible"
            
            # Test ServerSettings section
            server_section = config['ServerSettings']
            assert server_section['ServerAdminPassword'] == 'testpass', "ServerAdminPassword should be accessible"
            
        finally:
            os.unlink(f.name)
    
    print("✓ IniConfigHelper duplicate keys tests passed")


def test_mod_database():
    """Test mod database functionality."""
    print("Testing ModDatabase...")


def test_cli_mods_string():
    """Test the hidden 'mods-string' CLI helper outputs correct formatting."""
    print("Testing CLI mods-string helper...")
    
    # Clear any existing temp files
    import tempfile
    import shutil
    
    # Use a completely different temp directory
    with tempfile.TemporaryDirectory(prefix='asa_test_cli_') as temp_dir:
        db_path = os.path.join(temp_dir, 'test_cli_mods.json')
        
        # Reset singleton and set new path
        ModDatabase._reset_instance()
        
        # Create a fresh database instance with explicit path
        db = ModDatabase(db_path)
        
        # Enable mods
        db.enable_mod(111)
        db.enable_mod(222)
        
        # Update environment for CLI call and reset singleton again
        old_path = os.environ.get('ASA_MOD_DATABASE_PATH')
        os.environ['ASA_MOD_DATABASE_PATH'] = db_path
        ModDatabase._reset_instance()
        
        try:
            # Capture stdout
            from io import StringIO
            import contextlib
            buf = StringIO()
            with contextlib.redirect_stdout(buf):
                cli_main(['mods-string'])
            out = buf.getvalue().strip()
            assert out in ('-mods=111,222', '-mods=222,111')  # order not guaranteed
        finally:
            # Restore environment
            if old_path:
                os.environ['ASA_MOD_DATABASE_PATH'] = old_path
            else:
                os.environ.pop('ASA_MOD_DATABASE_PATH', None)
            ModDatabase._reset_instance()
            
    print("✓ CLI mods-string tests passed")

    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = os.path.join(temp_dir, "mods.json")
        db = ModDatabase(db_path)
        assert len(db.get_all_mods()) == 0

        db.enable_mod(12345)
        db.enable_mod(67890)

        first = db.get_mod(12345)
        assert isinstance(first, ModRecord)
        serialized = first.to_dict()
        restored = ModRecord.from_dict(serialized)
        assert restored.mod_id == first.mod_id

        enabled_mods = db.get_enabled_mods()
        assert len(enabled_mods) == 2
        assert {m.mod_id for m in enabled_mods} == {12345, 67890}

        # Disable and verify
        db.disable_mod(12345)
        enabled_mods = db.get_enabled_mods()
        assert len(enabled_mods) == 1
        assert enabled_mods[0].mod_id == 67890

    print("✓ ModDatabase tests passed")


def test_exit_codes():
    print("Testing ExitCodes...")
    assert ExitCodes.OK == 0
    assert ExitCodes.CORRUPTED_MODS_DATABASE == 1
    assert ExitCodes.MOD_ALREADY_ENABLED == 2
    assert ExitCodes.RCON_PASSWORD_NOT_FOUND == 3
    assert ExitCodes.RCON_PASSWORD_WRONG == 4
    assert ExitCodes.RCON_COMMAND_EXECUTION_FAILED == 5
    print("✓ ExitCodes tests passed")


def test_enterprise_features():
    """Test basic enterprise functionality."""
    print("Testing Enterprise features...")
    
    try:
        # Test configuration manager
        from asa_ctrl.enterprise import get_config_manager
        config_manager = get_config_manager()
        config = config_manager.get_config()
        assert config.server_name == "ASA Enterprise Server"
        assert config.max_players == 50
        print("  ✓ Configuration management working")
        
        # Test health checker
        from asa_ctrl.enterprise import get_health_checker
        health_checker = get_health_checker()
        health = health_checker.check_system_health()
        assert "status" in health
        assert "checks" in health
        print("  ✓ Health checker working")
        
        # Test metrics collector
        from asa_ctrl.enterprise import get_metrics_collector
        metrics_collector = get_metrics_collector()
        metrics = metrics_collector.collect_metrics()
        assert "timestamp" in metrics
        assert "hostname" in metrics
        print("  ✓ Metrics collector working")
        
        # Test audit logger
        from asa_ctrl.enterprise import get_audit_logger
        audit_logger = get_audit_logger()
        audit_logger.log_event("test_event", {"test": "data"})
        print("  ✓ Audit logger working")
        
    except Exception as e:
        print(f"  ✗ Enterprise features test failed: {e}")
        raise
        
    print("✓ Enterprise features tests passed")


def main():  # pragma: no cover - simple runner
    print("Running asa_ctrl tests...\n")
    try:
        test_start_params_helper()
        test_ini_config_helper_duplicate_keys()
        test_mod_database()
        test_cli_mods_string()
        test_exit_codes()
        test_enterprise_features()
        print("\nAll tests passed.")
        return 0
    except Exception as e:  # noqa: BLE001
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
