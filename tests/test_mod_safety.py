"""Regression coverage for preserving the configured world's mod set."""

import logging
import multiprocessing

import pytest

from asa_ctrl.common.config import AsaSettings
from asa_ctrl.common.errors import CorruptedModsDatabaseError
from asa_ctrl.common.launch_config import LaunchConfiguration
from asa_ctrl.core.mods import ModDatabase
from server_runtime import params
from asa_ctrl.core import mods


@pytest.mark.parametrize("contents", [b'[{"mod_id": "invalid"}]', b'\xff'])
def test_invalid_database_has_actionable_error(tmp_path, contents):
    path = tmp_path / "mods.json"
    path.write_bytes(contents)
    with pytest.raises(CorruptedModsDatabaseError):
        ModDatabase(str(path))
    assert path.read_bytes() == contents


def test_unreadable_mod_database_prevents_launch(monkeypatch):
    def denied(_settings):
        raise PermissionError("read denied")

    monkeypatch.setattr(params, "get_enabled_mod_ids", denied)
    config = LaunchConfiguration.parse("Map?listen -mods=123")
    with pytest.raises(CorruptedModsDatabaseError, match="permissions"):
        params._inject_dynamic_mods(config, AsaSettings({}), logging.getLogger("test"))
    assert config.render() == "Map?listen -mods=123"


def test_stale_instances_preserve_each_others_changes(tmp_path):
    path = str(tmp_path / "mods.json")
    first = ModDatabase(path)
    second = ModDatabase(path)
    first.enable_mod(1)
    second.enable_mod(2)
    first.disable_mod(2)
    assert {mod.mod_id: mod.enabled for mod in second.get_all_mods()} == {1: True, 2: False}
    second.remove_mod(1)
    assert not first.mod_exists(1)


def test_failed_atomic_replace_preserves_database(tmp_path, monkeypatch):
    path = tmp_path / "mods.json"
    database = ModDatabase(str(path))
    database.enable_mod(1)
    previous = path.read_bytes()

    def fail_replace(_source, _destination):
        raise OSError("simulated replacement failure")

    monkeypatch.setattr(mods.os, "replace", fail_replace)
    with pytest.raises(OSError, match="replacement failure"):
        database.enable_mod(2)
    assert path.read_bytes() == previous
    assert list(tmp_path.glob("*.tmp")) == []
    assert [mod.mod_id for mod in database.get_all_mods()] == [1]


def _enable_in_process(path, offset, barrier):
    database = ModDatabase(path)
    barrier.wait(timeout=30)
    for mod_id in range(offset, offset + 10):
        database.enable_mod(mod_id)


def test_concurrent_processes_preserve_all_mods(tmp_path):
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(4)
    path = str(tmp_path / "mods.json")
    processes = [
        context.Process(target=_enable_in_process, args=(path, offset, barrier))
        for offset in (10, 20, 30, 40)
    ]
    try:
        for process in processes:
            process.start()
        for process in processes:
            process.join(timeout=45)
            assert process.exitcode == 0
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
    assert {mod.mod_id for mod in ModDatabase(path).get_enabled_mods()} == set(range(10, 50))
