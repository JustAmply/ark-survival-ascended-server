#!/usr/bin/env python3
"""Test suite for asa_ctrl package.

Migrated from repository root to tests/ directory.
Run with: `py -m tests.test_asa_ctrl` or `py tests/test_asa_ctrl.py`.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from asa_ctrl.mods import ModDatabase, ModRecord  # noqa: E402
from asa_ctrl.config import StartParamsHelper, parse_start_params  # noqa: E402
from asa_ctrl.constants import ExitCodes  # noqa: E402
from asa_ctrl.cli import main as cli_main  # noqa: E402
from asa_ctrl.rcon import RconClient  # noqa: E402
from asa_ctrl.errors import (  # noqa: E402
    RconPortNotFoundError, 
    RconPasswordNotFoundError,
    RconConnectionError,
    RconPacketError,
    RconTimeoutError
)


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
    
    temp_path = None

    try:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.ini', delete=False) as f:
            f.write(ini_content)
            f.flush()
            temp_path = f.name

        # This should now work with the fix (strict=False)
        config = IniConfigHelper.parse_ini(temp_path)
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
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)
    
    print("✓ IniConfigHelper duplicate keys tests passed")


def test_mod_database():
    """Test mod database functionality."""
    print("Testing ModDatabase...")


def test_cli_mods_string():
    """Test the hidden 'mods-string' CLI helper outputs correct formatting."""
    print("Testing CLI mods-string helper...")
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = os.path.join(temp_dir, 'mods.json')
        os.environ['ASA_MOD_DATABASE_PATH'] = db_path
        try:
            db = ModDatabase.get_instance()
            db.enable_mod(111)
            db.enable_mod(222)
            # Capture stdout
            from io import StringIO
            import contextlib
            buf = StringIO()
            with contextlib.redirect_stdout(buf):
                cli_main(['mods-string'])
            out = buf.getvalue().strip()
            assert out in ('-mods=111,222', '-mods=222,111')  # order not guaranteed
        finally:
            os.environ.pop('ASA_MOD_DATABASE_PATH', None)
    print("\u2713 CLI mods-string tests passed")

    print("Testing CLI mods removal...")
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = os.path.join(temp_dir, 'mods.json')
        os.environ['ASA_MOD_DATABASE_PATH'] = db_path
        try:
            db = ModDatabase.get_instance()

            mod_id = 98765
            db.enable_mod(mod_id)
            assert db.get_mod(mod_id) is not None

            from io import StringIO
            import contextlib

            buf = StringIO()
            with contextlib.redirect_stdout(buf):
                cli_main(['mods', 'remove', str(mod_id)])
            assert db.get_mod(mod_id) is None
            output = buf.getvalue()
            assert "Removed mod id" in output
        finally:
            os.environ.pop('ASA_MOD_DATABASE_PATH', None)

    print("\u2713 CLI mods removal tests passed")

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


def test_mod_database_get_instance_respects_env():
    """Ensure ModDatabase singleton honours environment overrides."""
    print("Testing ModDatabase.get_instance() with environment override...")
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / 'mods.json'
        os.environ['ASA_MOD_DATABASE_PATH'] = str(db_path)
        try:
            db = ModDatabase.get_instance()
            assert db.database_path == db_path

            db.enable_mod(42)
            assert db.database_path.exists()

            same_db = ModDatabase.get_instance()
            assert same_db is db
        finally:
            os.environ.pop('ASA_MOD_DATABASE_PATH', None)

    print("✓ ModDatabase.get_instance() environment override tests passed")


def test_exit_codes():
    print("Testing ExitCodes...")
    assert ExitCodes.OK == 0
    assert ExitCodes.CORRUPTED_MODS_DATABASE == 1
    assert ExitCodes.MOD_ALREADY_ENABLED == 2
    assert ExitCodes.RCON_PASSWORD_NOT_FOUND == 3
    assert ExitCodes.RCON_PASSWORD_WRONG == 4
    assert ExitCodes.RCON_COMMAND_EXECUTION_FAILED == 5
    assert ExitCodes.RCON_CONNECTION_FAILED == 6
    assert ExitCodes.RCON_PACKET_ERROR == 7
    assert ExitCodes.RCON_TIMEOUT == 8
    print("✓ ExitCodes tests passed")


def test_rcon_validation():
    """Test RCON client validation functions."""
    print("Testing RCON validation...")
    
    # Create client instance without initialization to test individual methods
    client = RconClient.__new__(RconClient)
    client.MAX_COMMAND_LENGTH = 1000
    
    # Test IP validation
    assert client._validate_ip('127.0.0.1') == '127.0.0.1'
    assert client._validate_ip('localhost') == 'localhost'
    
    try:
        client._validate_ip('')
        assert False, "Should have raised ValueError for empty IP"
    except ValueError:
        pass  # Expected
    
    try:
        client._validate_ip(None)  # type: ignore
        assert False, "Should have raised ValueError for None IP"
    except ValueError:
        pass  # Expected
    
    # Test command validation
    assert client._validate_command('saveworld') == 'saveworld'
    assert client._validate_command('  broadcast Hello  ') == 'broadcast Hello'
    
    try:
        client._validate_command('')
        assert False, "Should have raised ValueError for empty command"
    except ValueError:
        pass  # Expected
    
    try:
        client._validate_command('x' * 2000)  # Too long
        assert False, "Should have raised ValueError for long command"
    except ValueError:
        pass  # Expected
    
    try:
        client._validate_command('\x00\x01\x02')  # Control characters
        assert False, "Should have raised ValueError for control characters only"
    except ValueError:
        pass  # Expected
    
    # Test packet validation
    try:
        client._validate_packet_data(b'')
        assert False, "Should have raised RconPacketError for empty data"
    except RconPacketError:
        pass  # Expected
    
    try:
        client._validate_packet_data(b'abc')  # Too small
        assert False, "Should have raised RconPacketError for small packet"
    except RconPacketError:
        pass  # Expected
    
    print("✓ RCON validation tests passed")


def main():  # pragma: no cover - simple runner
    print("Running asa_ctrl tests...\n")
    try:
        test_start_params_helper()
        test_ini_config_helper_duplicate_keys()
        test_mod_database()
        test_rcon_validation()
        test_exit_codes()
        print("\nAll tests passed.")
        return 0
    except Exception as e:  # noqa: BLE001
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
