#!/usr/bin/env python3
"""Behavioral contracts for the asa_ctrl package and CLI."""

from __future__ import annotations

import json
import os
import sys
import logging
import struct
import socket
import time
from unittest.mock import Mock

import pytest

# Ensure project root is on sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import asa_ctrl as asa_ctrl_package  # noqa: E402
from asa_ctrl.core.mods import ModDatabase, ModRecord, format_mod_list_for_server  # noqa: E402
from asa_ctrl.common.config import AsaSettings, parse_ini  # noqa: E402
from asa_ctrl.common.constants import ExitCodes  # noqa: E402
from asa_ctrl.common.logging_config import configure_logging  # noqa: E402
from asa_ctrl.cli_helpers import exit_with_error, map_exception_to_exit_code  # noqa: E402
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


def test_parse_ini_tolerates_duplicate_keys(tmp_path):
    """ARK writes duplicate INI keys; the last value wins."""
    ini_path = tmp_path / "GameUserSettings.ini"
    ini_path.write_text(
        "[/Script/ShooterGame.ShooterGameUserSettings]\n"
        "LastJoinedSessionPerCategory=\n"
        "LastJoinedSessionPerCategory=test_value\n"
        "RCONPort=27020\n\n"
        "[ServerSettings]\nServerAdminPassword=testpass\n",
        encoding="utf-8",
    )
    config = parse_ini(str(ini_path))
    assert config is not None
    assert config['/Script/ShooterGame.ShooterGameUserSettings']['LastJoinedSessionPerCategory'] == 'test_value'
    assert config['/Script/ShooterGame.ShooterGameUserSettings']['RCONPort'] == '27020'
    assert config['ServerSettings']['ServerAdminPassword'] == 'testpass'


def test_mod_database_mutations_persist(tmp_path):
    db_path = tmp_path / "mods.json"
    db = ModDatabase(str(db_path))
    assert db.get_all_mods() == []

    db.enable_mod(123)
    assert ModDatabase(str(db_path)).is_mod_enabled(123)
    db.disable_mod(123)
    assert not ModDatabase(str(db_path)).is_mod_enabled(123)
    db.enable_mod(123)
    assert ModDatabase(str(db_path)).is_mod_enabled(123)
    assert db.remove_mod(123)
    assert ModDatabase(str(db_path)).get_all_mods() == []


def test_mod_database_loads_legacy_records_with_defaults(tmp_path):
    db_path = tmp_path / "mods.json"
    db_path.write_text('[{"mod_id": 12345}, {"mod_id": 67890, "enabled": true}]', encoding="utf-8")
    db = ModDatabase(str(db_path))
    assert db.get_all_mods() == [
        ModRecord(12345, name="unknown", enabled=False, scanned=False),
        ModRecord(67890, name="unknown", enabled=True, scanned=False),
    ]
    assert [mod.mod_id for mod in db.get_enabled_mods()] == [67890]


def test_cli_mods_string(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "mods.json"
    monkeypatch.setenv('ASA_MOD_DATABASE_PATH', str(db_path))
    db = ModDatabase(str(db_path))
    db.enable_mod(111)
    db.enable_mod(222)
    db.disable_mod(111)

    cli_main(['mods-string'])

    # The runtime consumes stdout as one raw token, without a newline.
    assert capsys.readouterr().out == '-mods=222'


def test_cli_mods_remove_persists(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "mods.json"
    monkeypatch.setenv('ASA_MOD_DATABASE_PATH', str(db_path))
    db = ModDatabase(str(db_path))
    db.enable_mod(98765)

    cli_main(['mods', 'remove', '98765'])

    assert ModDatabase(str(db_path)).get_mod(98765) is None
    assert "Removed mod id" in capsys.readouterr().out


def test_mod_database_from_settings_respects_env(tmp_path, monkeypatch):
    db_path = tmp_path / 'mods.json'
    monkeypatch.setenv('ASA_MOD_DATABASE_PATH', str(db_path))
    db = ModDatabase.from_settings()
    assert db.database_path == db_path
    db.enable_mod(42)
    assert ModDatabase(str(db_path)).is_mod_enabled(42)


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


@pytest.mark.parametrize("enabled", [[], [200, 100]])
def test_format_mod_list_for_server(tmp_path, enabled):
    db_path = tmp_path / "mods.json"
    settings = AsaSettings({"ASA_MOD_DATABASE_PATH": str(db_path)})
    db = ModDatabase.from_settings(settings)
    for mod_id in enabled:
        db.enable_mod(mod_id)
    output = format_mod_list_for_server(settings)
    if not enabled:
        assert output == ""
    else:
        assert output in ("-mods=200,100", "-mods=100,200")


def test_exit_codes():
    assert ExitCodes.OK == 0
    assert ExitCodes.CORRUPTED_MODS_DATABASE == 1
    assert ExitCodes.MOD_ALREADY_ENABLED == 2
    assert ExitCodes.RCON_PASSWORD_NOT_FOUND == 3
    assert ExitCodes.RCON_PASSWORD_WRONG == 4
    assert ExitCodes.RCON_COMMAND_EXECUTION_FAILED == 5
    assert ExitCodes.RCON_CONNECTION_FAILED == 6
    assert ExitCodes.RCON_PACKET_ERROR == 7
    assert ExitCodes.RCON_TIMEOUT == 8


def test_logging_config_env_and_explicit(monkeypatch):
    monkeypatch.setenv("ASA_LOG_LEVEL", "DEBUG")
    root_logger = logging.getLogger()
    previous_level = root_logger.level
    # Do not close pytest's existing handlers when exercising force=True.
    monkeypatch.setattr(root_logger, "handlers", [])
    try:
        configure_logging(force=True)
        assert root_logger.level == logging.DEBUG

        configure_logging(level="WARNING", force=True)
        assert root_logger.level == logging.WARNING
    finally:
        for handler in root_logger.handlers:
            handler.close()
        root_logger.setLevel(previous_level)


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


@pytest.mark.parametrize("server_ip", ["127.0.0.1", "localhost"])
def test_rcon_client_accepts_ip_and_hostname(server_ip):
    assert RconClient(server_ip, port=27020, password="secret").server_ip == server_ip


@pytest.mark.parametrize("server_ip", ["", None])
def test_rcon_client_rejects_empty_address(server_ip):
    with pytest.raises(ValueError, match="IP address"):
        RconClient(server_ip, port=27020, password="secret")


def test_rcon_connect_propagates_auth_failure(monkeypatch):
    """Decode a wire-level signed -1, rather than providing a decoded packet."""
    client = RconClient(port=27020, password='secret', retry_count=0)
    transport = Mock()
    transport.recv.side_effect = [
        bytes.fromhex('0a00'), bytes.fromhex('0000'),
        bytes.fromhex('ffffffff020000000000'),
    ]
    monkeypatch.setattr('asa_ctrl.core.rcon.socket.socket', lambda *_args: transport)
    monkeypatch.setattr(time, 'time', lambda: 123)

    with pytest.raises(RconAuthenticationError, match="-1 response ID"):
        client.connect()

    assert not client.is_connected()
    transport.sendall.assert_called_once_with(
        bytes.fromhex('100000007b000000030000007365637265740000')
    )


def test_rcon_identify_port_rejects_invalid_start_params():
    settings = AsaSettings({'ASA_START_PARAMS': 'TheIsland_WP?listen?RCONPort=notanint'})
    with pytest.raises(RconPortNotFoundError, match="Invalid port in start parameters: notanint"):
        RconClient(password="secret", retry_count=0, settings=settings)


def test_rcon_packet_codec_encodes_protocol_bytes():
    assert RconPacketCodec(4096, 12).encode(123, 2, "saveworld") == bytes.fromhex(
        '130000007b0000000200000073617665776f726c640000'
    )


def test_rcon_packet_codec_decodes_protocol_bytes():
    decoded = RconPacketCodec(4096, 12).decode(
        bytes.fromhex('130000007b0000000000000073617665776f726c640000')
    )
    assert decoded == RconPacket(19, 123, 0, "saveworld")


@pytest.mark.parametrize("packet", [b'', b'abc', bytes.fromhex('0d000000010000000200000068690000')])
def test_rcon_packet_codec_rejects_invalid_frames(packet):
    with pytest.raises(RconPacketError):
        RconPacketCodec(4096, 12).decode(packet)


def test_rcon_identify_password_from_start_params():
    settings = AsaSettings(
        {
            "ASA_START_PARAMS": "TheIsland_WP?listen?ServerAdminPassword=fromparams",
        }
    )
    client = RconClient(port=27020, settings=settings)
    assert client.password == "fromparams"


def test_rcon_identify_password_from_discrete_env():
    """asa-ctrl rcon must find the password when the stack uses ASA_SERVER_ADMIN_PASSWORD."""
    settings = AsaSettings({"ASA_SERVER_ADMIN_PASSWORD": "fromenv"})
    client = RconClient(port=27020, settings=settings)
    assert client.password == "fromenv"


def test_rcon_discrete_env_overrides_legacy_start_params():
    settings = AsaSettings(
        {
            "ASA_START_PARAMS": "TheIsland_WP?listen?ServerAdminPassword=old?RCONPort=27020",
            "ASA_SERVER_ADMIN_PASSWORD": "new",
            "ASA_RCON_PORT": "27030",
        }
    )
    client = RconClient(settings=settings)
    assert client.password == "new"
    assert client.port == 27030


def test_rcon_identify_port_from_discrete_env():
    settings = AsaSettings(
        {"ASA_RCON_PORT": "27021", "ASA_SERVER_ADMIN_PASSWORD": "secret"}
    )
    client = RconClient(settings=settings)
    assert client.port == 27021


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


def test_rcon_connect_retries_after_timeout(monkeypatch):
    client = RconClient(port=27020, password="secret", retry_count=1, retry_delay=0.01)
    failed_transport, retry_transport = Mock(), Mock()
    failed_transport.connect.side_effect = socket.timeout("no response")
    retry_transport.recv.side_effect = [
        bytes.fromhex('0a000000'), bytes.fromhex('7b000000020000000000'),
    ]
    monkeypatch.setattr('asa_ctrl.core.rcon.socket.socket', Mock(side_effect=[failed_transport, retry_transport]))
    sleeps = []
    monkeypatch.setattr(time, "sleep", sleeps.append)

    client.connect()

    assert client.is_connected()
    failed_transport.close.assert_called_once()
    assert sleeps == [0.1]
    client.close()
    retry_transport.close.assert_called_once()
    assert not client.is_connected()


@pytest.mark.parametrize(
    ("chunks", "error"),
    [
        ([struct.pack("<I", 9)], "Invalid packet size"),
        ([struct.pack("<I", 4093)], "Packet size too large"),
        ([struct.pack("<I", 10), b"short", b""], "Connection closed"),
        ([b"ab", b""], "Connection closed"),
    ],
)
def test_rcon_connect_rejects_bad_or_truncated_frames(chunks, error, monkeypatch):
    client = RconClient(port=27020, password="secret", retry_count=0)
    transport = Mock()
    transport.recv.side_effect = chunks
    monkeypatch.setattr('asa_ctrl.core.rcon.socket.socket', lambda *_args: transport)

    with pytest.raises((RconPacketError, RconConnectionError), match=error):
        client.connect()
    assert not client.is_connected()


@pytest.mark.parametrize("command", ["", "x" * 2000, "\x00\x01\x02"])
def test_rcon_execute_command_rejects_invalid_command_before_connect(command, monkeypatch):
    def unexpected_client(*_args, **_kwargs):
        pytest.fail("Invalid command reached the network client")

    monkeypatch.setattr("asa_ctrl.core.rcon.RconClient", unexpected_client)
    with pytest.raises(ValueError):
        execute_rcon_command(command)


def test_execute_rcon_command_uses_client(monkeypatch):
    responses = []
    captured = {}

    class DummyClient:
        def __init__(self, server_ip, *, settings=None):
            captured["server_ip"] = server_ip
            captured["settings"] = settings

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def execute_command(self, command):
            responses.append(command)
            return "ok"

    monkeypatch.setattr("asa_ctrl.core.rcon.RconClient", DummyClient)
    settings = AsaSettings({})
    assert execute_rcon_command("  listplayers  ", "ark.local", settings=settings) == "ok"
    assert responses == ["listplayers"]
    assert captured == {"server_ip": "ark.local", "settings": settings}


def test_rcon_client_root_export_has_compatibility_path():
    assert "RconClient" in asa_ctrl_package.__all__
    with pytest.warns(DeprecationWarning, match="asa_ctrl.RconClient is deprecated"):
        assert asa_ctrl_package.RconClient is RconClient


@pytest.mark.parametrize(
    "name, replacement",
    [
        ("StartParamsHelper", "LaunchConfiguration"),
        ("IniConfigHelper", "parse_ini"),
        ("parse_start_params", "LaunchConfiguration"),
    ],
)
def test_retired_config_helpers_stay_importable_and_warn(name, replacement):
    """The exported names keep working, and each warning names its replacement."""
    assert name in asa_ctrl_package.__all__
    with pytest.warns(DeprecationWarning, match=f"asa_ctrl.{name} is deprecated") as caught:
        resolved = getattr(asa_ctrl_package, name)

    assert resolved is not None
    assert replacement in str(caught[0].message)


def test_retired_helpers_still_delegate_to_the_live_modules():
    with pytest.warns(DeprecationWarning):
        helper = asa_ctrl_package.StartParamsHelper
    with pytest.warns(DeprecationWarning):
        legacy_parse = asa_ctrl_package.parse_start_params

    line = "TheIsland_WP?listen?RCONPort=27020"
    assert helper.get_value(line, "RCONPort") == "27020"
    assert legacy_parse(line) == {"_map": "TheIsland_WP", "RCONPort": "27020"}


def test_unknown_root_attribute_still_raises():
    with pytest.raises(AttributeError, match="has no attribute 'NotAThing'"):
        asa_ctrl_package.NotAThing


def test_cli_main_no_args_shows_help(capsys):
    with pytest.raises(SystemExit) as exc:
        cli_main([])
    assert exc.value.code == ExitCodes.OK
    captured = capsys.readouterr()
    assert "Available commands" in captured.out


def test_cli_help_lists_only_public_commands(capsys):
    with pytest.raises(SystemExit) as exc:
        cli_main(["--help"])

    assert exc.value.code == ExitCodes.OK
    output = capsys.readouterr().out
    assert "{rcon,mods}" in output
    assert "mods-string" not in output
    assert "restart-scheduler" not in output


def test_cli_debug_log_hides_launch_password(monkeypatch, caplog):
    monkeypatch.setenv("ASA_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("ASA_START_PARAMS", "Map?ServerAdminPassword=cli-secret?Port=7777")

    with caplog.at_level(logging.DEBUG, logger="asa_ctrl.cli"):
        with pytest.raises(SystemExit):
            cli_main(["mods"])

    assert "ServerAdminPassword=<redacted>" in caplog.text
    assert "cli-secret" not in caplog.text


def test_cli_mods_no_action_prints_help(capsys):
    with pytest.raises(SystemExit) as exc:
        cli_main(["mods"])
    assert exc.value.code == ExitCodes.OK
    captured = capsys.readouterr()
    assert "Please specify a mod action" in captured.out


def test_cli_mods_enable_disable_persists(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "mods.json"
    monkeypatch.setenv("ASA_MOD_DATABASE_PATH", str(db_path))

    cli_main(["mods", "enable", "123"])
    out = capsys.readouterr().out
    assert "Enabled mod id" in out
    assert ModDatabase(str(db_path)).is_mod_enabled(123)

    cli_main(["mods", "disable", "123"])
    out = capsys.readouterr().out
    assert "Disabled mod id" in out
    assert not ModDatabase(str(db_path)).is_mod_enabled(123)


@pytest.mark.parametrize("enabled_only", [False, True])
def test_cli_mods_list_filters_disabled_records(tmp_path, monkeypatch, capsys, enabled_only):
    db_path = tmp_path / "mods.json"
    monkeypatch.setenv("ASA_MOD_DATABASE_PATH", str(db_path))
    db = ModDatabase(str(db_path))
    db.enable_mod(123)
    db.enable_mod(456)
    db.disable_mod(456)

    cli_main(["mods", "list"] + (["--enabled-only"] if enabled_only else []))

    out = capsys.readouterr().out
    assert "123: unknown (enabled)" in out
    if enabled_only:
        assert "Enabled mods:" in out
        assert "456" not in out
    else:
        assert "All mods:" in out
        assert "456: unknown (disabled)" in out


def test_cli_mods_already_enabled_exit_code(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "mods.json"
    monkeypatch.setenv("ASA_MOD_DATABASE_PATH", str(db_path))
    db = ModDatabase(str(db_path))
    db.enable_mod(999)

    with pytest.raises(SystemExit) as exc:
        cli_main(["mods", "enable", "999"])
    assert exc.value.code == ExitCodes.MOD_ALREADY_ENABLED
    assert "already enabled" in capsys.readouterr().err.lower()


def test_rcon_command_errors_map_to_exit_codes(capsys, monkeypatch):
    def raise_password_error(_command):
        raise RconPasswordNotFoundError("missing")

    monkeypatch.setattr("asa_ctrl.cli_commands.rcon_command.execute_rcon_command", raise_password_error)
    with pytest.raises(SystemExit) as exc:
        cli_main(["rcon", "--exec", "listplayers"])
    assert exc.value.code == ExitCodes.RCON_PASSWORD_NOT_FOUND
    assert "could not read rcon password" in capsys.readouterr().err.lower()


def test_rcon_authentication_error_names_admin_password(capsys, monkeypatch):
    def raise_auth_error(_command):
        raise RconAuthenticationError("wrong password")

    monkeypatch.setattr("asa_ctrl.cli_commands.rcon_command.execute_rcon_command", raise_auth_error)
    with pytest.raises(SystemExit) as exc:
        cli_main(["rcon", "--exec", "listplayers"])

    assert exc.value.code == ExitCodes.RCON_PASSWORD_WRONG
    assert "ServerAdminPassword" in capsys.readouterr().err


def test_parse_ini_missing_file_returns_none(tmp_path):
    missing = tmp_path / "missing.ini"
    assert parse_ini(str(missing)) is None


def test_parse_ini_invalid_file_returns_none(tmp_path):
    invalid = tmp_path / "invalid.ini"
    invalid.write_text("missing section header", encoding="utf-8")
    assert parse_ini(str(invalid)) is None
