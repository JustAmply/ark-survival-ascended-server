#!/usr/bin/env python3
"""Test suite for asa_ctrl package.

Migrated from repository root to tests/ directory.
Run with: `py -m tests.test_asa_ctrl` or `py tests/test_asa_ctrl.py`.
"""

from __future__ import annotations

import os
import sys
import tempfile

# Ensure project root is on sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from asa_ctrl.mods import ModDatabase, ModRecord  # noqa: E402
from asa_ctrl.config import StartParamsHelper, parse_start_params  # noqa: E402
from asa_ctrl.constants import ExitCodes  # noqa: E402


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


def test_mod_database():
    """Test mod database functionality."""
    print("Testing ModDatabase...")

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


def main():  # pragma: no cover - simple runner
    print("Running asa_ctrl tests...\n")
    try:
        test_start_params_helper()
        test_mod_database()
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
