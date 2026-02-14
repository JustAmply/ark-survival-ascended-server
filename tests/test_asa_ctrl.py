#!/usr/bin/env python3
"""Test suite for asa_ctrl package.

Migrated from repository root to tests/ directory.
Run with: `py -m tests.test_asa_ctrl` or `py tests/test_asa_ctrl.py`.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import logging
import time
from pathlib import Path
from types import MethodType
from unittest.mock import patch

import pytest

# Ensure project root is on sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from asa_ctrl.core.mods import ModDatabase, ModRecord, format_mod_list_for_server  # noqa: E402
from asa_ctrl.common.config import AsaSettings, StartParamsHelper, parse_start_params  # noqa: E402
from asa_ctrl.common.constants import ExitCodes, get_mod_database_path  # noqa: E402
from asa_ctrl.common.logging_config import configure_logging  # noqa: E402
from asa_ctrl.cli_helpers import exit_with_error, map_exception_to_exit_code  # noqa: E402
from asa_ctrl.cli_commands.mods_command import ModsCommand  # noqa: E402
from asa_ctrl.cli_commands.rcon_command import RconCommand  # noqa: E402
from asa_ctrl.cli import main as cli_main  # noqa: E402
from asa_ctrl.core.rcon import RconClient, RconPacket, RconPacketCodec, execute_rcon_command  # noqa: E402
from asa_ctrl.common.errors import (  # noqa: E402
    RconPortNotFoundError,
    RconPasswordNotFoundError,
    RconConnectionError,
    RconPacketError,
    RconTimeoutError,
    RconAuthenticationError,
    CorruptedModsDatabaseError,
    ModAlreadyEnabledError,
)
from asa_ctrl.common.constants import RconPacketTypes  # noqa: E402


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

    print("OK StartParamsHelper tests passed")


def test_ini_config_helper_duplicate_keys():
    """Test that IniConfigHelper handles duplicate keys in INI files gracefully."""
    print("Testing IniConfigHelper with duplicate keys...")

    from asa_ctrl.common.config import IniConfigHelper

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

    print("OK IniConfigHelper duplicate keys tests passed")


def test_mod_database():
    """Test mod database functionality."""
    print("Testing ModDatabase...")
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = os.path.join(temp_dir, "mods.json")
        db = ModDatabase(db_path)
        assert db.get_all_mods() == []

        db.enable_mod(123)
        assert db.mod_exists(123) is True
        assert db.is_mod_enabled(123) is True

        # Enabling an existing disabled mod should flip the flag.
        db.disable_mod(123)
        assert db.is_mod_enabled(123) is False
        db.enable_mod(123)
        assert db.is_mod_enabled(123) is True

        # Remove and verify persistence to disk by reloading.
        assert db.remove_mod(123) is True
        assert db.get_mod(123) is None
        reloaded = ModDatabase(db_path)
        assert reloaded.get_all_mods() == []


def test_cli_mods_string():
    """Test the hidden 'mods-string' CLI helper outputs correct formatting."""
    print("Testing CLI mods-string helper...")
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = os.path.join(temp_dir, 'mods.json')
        os.environ['ASA_MOD_DATABASE_PATH'] = db_path
        try:
            db = ModDatabase(db_path)
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
    print("OK CLI mods-string tests passed")

    print("Testing CLI mods removal...")
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = os.path.join(temp_dir, 'mods.json')
        os.environ['ASA_MOD_DATABASE_PATH'] = db_path
        try:
            db = ModDatabase(db_path)

            mod_id = 98765
            db.enable_mod(mod_id)
            assert db.get_mod(mod_id) is not None

            from io import StringIO
            import contextlib

            buf = StringIO()
            with contextlib.redirect_stdout(buf):
                cli_main(['mods', 'remove', str(mod_id)])
            refreshed = ModDatabase(db_path)
            assert refreshed.get_mod(mod_id) is None
            output = buf.getvalue()
            assert "Removed mod id" in output
        finally:
            os.environ.pop('ASA_MOD_DATABASE_PATH', None)

    print("OK CLI mods removal tests passed")

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

    print("OK ModDatabase tests passed")


def test_mod_database_from_settings_respects_env():
    """Ensure ModDatabase respects environment overrides."""
    print("Testing ModDatabase.from_settings() with environment override...")
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / 'mods.json'
        os.environ['ASA_MOD_DATABASE_PATH'] = str(db_path)
        try:
            db = ModDatabase.from_settings()
            assert db.database_path == db_path

            db.enable_mod(42)
            assert db.database_path.exists()
        finally:
            os.environ.pop('ASA_MOD_DATABASE_PATH', None)

    print("OK ModDatabase.from_settings() environment override tests passed")


def test_mod_database_load_rejects_non_list_json(tmp_path):
    """Ensure malformed mods.json without a list triggers a helpful error."""

    db_path = tmp_path / "mods.json"
    db_path.write_text(json.dumps({"mod_id": 1}), encoding="utf-8")

    with pytest.raises(CorruptedModsDatabaseError) as exc:
        ModDatabase(str(db_path))

    assert "JSON array" in str(exc.value)


def test_mod_database_load_rejects_non_mapping_entries(tmp_path):
    """Ensure mods.json entries must be objects with required keys."""

    db_path = tmp_path / "mods.json"
    db_path.write_text(json.dumps(["invalid"]), encoding="utf-8")

    with pytest.raises(CorruptedModsDatabaseError) as exc:
        ModDatabase(str(db_path))

    assert "index 0" in str(exc.value)


def test_mod_database_load_reports_missing_keys(tmp_path):
    """Ensure missing required keys produce a descriptive corruption error."""

    db_path = tmp_path / "mods.json"
    db_path.write_text(json.dumps([{ "name": "No ID" }]), encoding="utf-8")

    with pytest.raises(CorruptedModsDatabaseError) as exc:
        ModDatabase(str(db_path))

    message = str(exc.value)
    assert "index 0" in message
    assert "mod_id" in message


def test_mod_database_load_rejects_bad_json(tmp_path):
    db_path = tmp_path / "mods.json"
    db_path.write_text("not-json", encoding="utf-8")

    with pytest.raises(CorruptedModsDatabaseError) as exc:
        ModDatabase(str(db_path))

    assert "mods.json file is corrupted" in str(exc.value)


def test_format_mod_list_for_server_empty(tmp_path):
    db_path = tmp_path / "mods.json"
    os.environ["ASA_MOD_DATABASE_PATH"] = str(db_path)
    try:
        assert format_mod_list_for_server() == ""
    finally:
        os.environ.pop("ASA_MOD_DATABASE_PATH", None)


def test_format_mod_list_for_server_sorted_ids(tmp_path):
    db_path = tmp_path / "mods.json"
    os.environ["ASA_MOD_DATABASE_PATH"] = str(db_path)
    try:
        db = ModDatabase(str(db_path))
        db.enable_mod(200)
        db.enable_mod(100)
        output = format_mod_list_for_server()
        assert output in ("-mods=200,100", "-mods=100,200")
    finally:
        os.environ.pop("ASA_MOD_DATABASE_PATH", None)


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
    print("OK ExitCodes tests passed")


def test_constants_get_mod_database_path_env_override(tmp_path):
    override_path = tmp_path / "mods.json"
    os.environ["ASA_MOD_DATABASE_PATH"] = str(override_path)
    try:
        assert get_mod_database_path() == str(override_path)
    finally:
        os.environ.pop("ASA_MOD_DATABASE_PATH", None)


def test_logging_config_env_and_explicit(monkeypatch):
    monkeypatch.setenv("ASA_LOG_LEVEL", "DEBUG")
    configure_logging(force=True)
    assert logging.getLogger().level == logging.DEBUG

    configure_logging(level="WARNING", force=True)
    assert logging.getLogger().level == logging.WARNING


def test_cli_helpers_exit_with_error(capsys):
    with pytest.raises(SystemExit) as exc:
        exit_with_error("boom", 7)
    assert exc.value.code == 7
    captured = capsys.readouterr()
    assert "Error: boom" in captured.err


def test_cli_helpers_map_exception_to_exit_code():
    assert map_exception_to_exit_code(RconPasswordNotFoundError("x")) == ExitCodes.RCON_PASSWORD_NOT_FOUND
    assert map_exception_to_exit_code(RconAuthenticationError("x")) == ExitCodes.RCON_PASSWORD_WRONG
    assert map_exception_to_exit_code(RconPortNotFoundError("x")) == ExitCodes.RCON_CONNECTION_FAILED
    assert map_exception_to_exit_code(RconConnectionError("x")) == ExitCodes.RCON_CONNECTION_FAILED
    assert map_exception_to_exit_code(RconTimeoutError("x")) == ExitCodes.RCON_TIMEOUT
    assert map_exception_to_exit_code(RconPacketError("x")) == ExitCodes.RCON_PACKET_ERROR
    assert map_exception_to_exit_code(ModAlreadyEnabledError("x")) == ExitCodes.MOD_ALREADY_ENABLED
    assert map_exception_to_exit_code(CorruptedModsDatabaseError("x")) == ExitCodes.CORRUPTED_MODS_DATABASE
    assert map_exception_to_exit_code(ValueError("x")) is None


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

    print("OK RCON validation tests passed")


def test_rcon_authenticate_failure_propagates_error():
    """Ensure _authenticate raises when the server reports a failure."""

    client = RconClient.__new__(RconClient)
    client.password = "test"
    client._authenticated = False
    client._connected = True

    def fake_send_packet(self, data, packet_type):
        assert packet_type == RconPacketTypes.AUTH
        return RconPacket(10, -1, RconPacketTypes.AUTH_RESPONSE, "")

    client._send_packet = MethodType(fake_send_packet, client)

    try:
        client._authenticate()
        assert False, "_authenticate should raise RconAuthenticationError on -1 response ID"
    except RconAuthenticationError:
        assert client._authenticated is False


def test_rcon_connect_propagates_auth_failure():
    """Ensure connect() surfaces authentication failures."""

    client = RconClient(server_ip='127.0.0.1', port=27020, password='secret', retry_count=0)

    def fake_send_packet(self, data, packet_type):
        assert packet_type == RconPacketTypes.AUTH
        return RconPacket(10, -1, RconPacketTypes.AUTH_RESPONSE, "")

    client._send_packet = MethodType(fake_send_packet, client)

    class DummySocket:
        def __init__(self, *args, **kwargs):
            self.closed = False

        def settimeout(self, value):  # pragma: no cover - trivial setter
            self.timeout = value

        def connect(self, address):  # pragma: no cover - trivial connector
            self.address = address

        def close(self):  # pragma: no cover - trivial closer
            self.closed = True

    with patch('asa_ctrl.core.rcon.socket.socket', return_value=DummySocket()):
        try:
            client.connect()
            assert False, "connect() should raise RconAuthenticationError when auth fails"
        except RconAuthenticationError:
            assert client._authenticated is False


def test_rcon_identify_port_rejects_invalid_start_params():
    """Ensure invalid start parameter ports surface a consistent error."""
    os.environ['ASA_START_PARAMS'] = "TheIsland_WP?listen?RCONPort=notanint"
    try:
        with pytest.raises(RconPortNotFoundError) as exc:
            RconClient(port=None, password="secret", retry_count=0)
        assert "Invalid port in start parameters: notanint" in str(exc.value)
    finally:
        os.environ.pop('ASA_START_PARAMS', None)


def test_rcon_packet_codec_round_trip():
    codec = RconPacketCodec(4096, 12)
    packet = codec.encode(123, RconPacketTypes.EXEC_COMMAND, "saveworld")
    decoded = codec.decode(packet)
    assert decoded.id == 123
    assert decoded.type == RconPacketTypes.EXEC_COMMAND
    assert decoded.body == "saveworld"


def test_rcon_packet_codec_rejects_size_mismatch():
    codec = RconPacketCodec(4096, 12)
    packet = bytearray(codec.encode(1, RconPacketTypes.EXEC_COMMAND, "hi"))
    # Corrupt size to force mismatch
    packet[0] = packet[0] + 1
    with pytest.raises(RconPacketError):
        codec.decode(bytes(packet))


def test_rcon_identify_password_from_start_params():
    settings = AsaSettings(
        {
            "ASA_START_PARAMS": "TheIsland_WP?listen?ServerAdminPassword=fromparams",
        }
    )
    client = RconClient(port=27020, settings=settings)
    assert client.password == "fromparams"


def test_rcon_identify_password_from_ini(tmp_path):
    ini_path = tmp_path / "GameUserSettings.ini"
    ini_path.write_text(
        "[ServerSettings]\nServerAdminPassword=fromini\nRCONPort=27020\n",
        encoding="utf-8",
    )
    settings = AsaSettings(
        {
            "ASA_GAME_USER_SETTINGS_PATH": str(ini_path),
        }
    )
    client = RconClient(port=27020, settings=settings)
    assert client.password == "fromini"


def test_rcon_identify_port_from_ini(tmp_path):
    ini_path = tmp_path / "GameUserSettings.ini"
    ini_path.write_text(
        "[ServerSettings]\nServerAdminPassword=fromini\nRCONPort=27021\n",
        encoding="utf-8",
    )
    settings = AsaSettings(
        {
            "ASA_GAME_USER_SETTINGS_PATH": str(ini_path),
        }
    )
    client = RconClient(password="secret", settings=settings, retry_count=0)
    assert client.port == 27021


def test_rcon_with_retry_resets_state(monkeypatch):
    client = RconClient.__new__(RconClient)
    client.retry_count = 1
    client.retry_delay = 0.01
    client._connected = True
    client._authenticated = True
    client.socket = None

    def fail_once():
        raise RconTimeoutError("nope")

    monkeypatch.setattr(time, "sleep", lambda _value: None)
    with pytest.raises(RconTimeoutError):
        client._with_retry(fail_once)
    assert client._connected is False
    assert client._authenticated is False


def test_rcon_receive_exact_reads_full_buffer():
    client = RconClient.__new__(RconClient)

    class DummySocket:
        def __init__(self):
            self.calls = 0

        def recv(self, size):
            self.calls += 1
            if self.calls == 1:
                return b"ab"
            return b"cd"

    client.socket = DummySocket()
    data = client._receive_exact(4)
    assert data == b"abcd"


def test_rcon_execute_command_raises_on_invalid_command():
    client = RconClient.__new__(RconClient)
    with pytest.raises(ValueError):
        client.execute_command("")


def test_execute_rcon_command_uses_client(monkeypatch):
    responses = []

    class DummyClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def execute_command(self, command):
            responses.append(command)
            return "ok"

    monkeypatch.setattr("asa_ctrl.core.rcon.RconClient", DummyClient)
    assert execute_rcon_command("listplayers") == "ok"
    assert responses == ["listplayers"]


def test_cli_main_no_args_shows_help(capsys):
    with pytest.raises(SystemExit) as exc:
        cli_main([])
    assert exc.value.code == ExitCodes.OK
    captured = capsys.readouterr()
    assert "Available commands" in captured.out


def test_cli_mods_no_action_prints_help(capsys):
    with pytest.raises(SystemExit) as exc:
        cli_main(["mods"])
    assert exc.value.code == ExitCodes.OK
    captured = capsys.readouterr()
    assert "Please specify a mod action" in captured.out


def test_mods_command_enable_disable_list(tmp_path, capsys):
    db_path = tmp_path / "mods.json"
    settings = AsaSettings({"ASA_MOD_DATABASE_PATH": str(db_path)})

    args = type("Args", (), {"mod_action": "enable", "mod_id": 123, "settings": settings})
    ModsCommand.execute(args)
    out = capsys.readouterr().out
    assert "Enabled mod id" in out

    args = type("Args", (), {"mod_action": "disable", "mod_id": 123, "settings": settings})
    ModsCommand.execute(args)
    out = capsys.readouterr().out
    assert "Disabled mod id" in out

    args = type("Args", (), {"mod_action": "list", "enabled_only": True, "settings": settings})
    ModsCommand.execute(args)
    out = capsys.readouterr().out
    assert "Enabled mods:" in out


def test_mods_command_already_enabled_exit_code(tmp_path, capsys):
    db_path = tmp_path / "mods.json"
    settings = AsaSettings({"ASA_MOD_DATABASE_PATH": str(db_path)})
    db = ModDatabase(str(db_path))
    db.enable_mod(999)

    args = type("Args", (), {"mod_action": "enable", "mod_id": 999, "settings": settings})
    with pytest.raises(SystemExit) as exc:
        ModsCommand.execute(args)
    assert exc.value.code == ExitCodes.MOD_ALREADY_ENABLED
    assert "already enabled" in capsys.readouterr().err.lower()


def test_rcon_command_errors_map_to_exit_codes(capsys, monkeypatch):
    def raise_password_error(_command):
        raise RconPasswordNotFoundError("missing")

    monkeypatch.setattr("asa_ctrl.cli_commands.rcon_command.execute_rcon_command", raise_password_error)
    args = type("Args", (), {"command": "listplayers"})
    with pytest.raises(SystemExit) as exc:
        RconCommand.execute(args)
    assert exc.value.code == ExitCodes.RCON_PASSWORD_NOT_FOUND
    assert "could not read rcon password" in capsys.readouterr().err.lower()


def test_ini_config_helper_missing_file_returns_none(tmp_path):
    missing = tmp_path / "missing.ini"
    from asa_ctrl.common.config import IniConfigHelper

    assert IniConfigHelper.parse_ini(str(missing)) is None


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
