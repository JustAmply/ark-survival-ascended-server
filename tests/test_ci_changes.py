"""Protect the CI selection boundary against accidentally skipped checks."""

import importlib.util
from pathlib import Path
import subprocess

import pytest


spec = importlib.util.spec_from_file_location(
    "ci_changes", Path(__file__).resolve().parents[1] / "scripts" / "ci_changes.py"
)
assert spec is not None and spec.loader is not None
ci_changes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci_changes)


@pytest.mark.parametrize(("paths", "expected"), [
    (["README.md", "docs/adr/0001-launch-configuration.md"], (False, False)),
    (["tests/test_server_runtime.py", "README.md"], (True, False)),
    # The project version also determines image tags and runtime metadata.
    (["pyproject.toml"], (True, True)),
    (["asa_ctrl/core/rcon.py"], (True, True)),
    (["server_runtime/supervisor.py"], (True, True)),
    (["Dockerfile"], (True, True)),
    (["scripts/verify_runtime_lifecycle.py"], (True, True)),
    ([".github/workflows/test-and-build.yml"], (True, True)),
    (["scripts/ci_changes.py"], (True, True)),
    (["README.md", "new-runtime-file"], (True, True)),
    ([], (True, True)),
])
def test_selects_required_checks(paths, expected):
    assert ci_changes.required_checks(paths) == expected


@pytest.mark.parametrize("base", [None, "not-a-commit", "0" * 40, "e" * 40])
def test_unusable_base_runs_all_checks(monkeypatch, tmp_path, base):
    output = tmp_path / "outputs"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("CI_EVENT_NAME", "push")
    monkeypatch.setenv("CI_REF_TYPE", "branch")
    if base is None:
        monkeypatch.delenv("CI_BASE_SHA", raising=False)
    else:
        monkeypatch.setenv("CI_BASE_SHA", base)
    ci_changes.main()
    assert output.read_text() == "python=true\ndocker=true\n"


def test_missing_git_runs_all_checks(monkeypatch, tmp_path):
    output = tmp_path / "outputs"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("CI_EVENT_NAME", "pull_request")
    monkeypatch.setenv("CI_REF_TYPE", "branch")
    monkeypatch.setenv("CI_BASE_SHA", "a" * 40)

    def fail_git(*args, **kwargs):
        raise FileNotFoundError("git unavailable")

    monkeypatch.setattr(ci_changes.subprocess, "run", fail_git)
    ci_changes.main()
    assert output.read_text() == "python=true\ndocker=true\n"


def test_documentation_change_appends_skipped_checks_to_github_output(monkeypatch, tmp_path):
    output = tmp_path / "outputs"
    output.write_text("existing=value\n")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("CI_EVENT_NAME", "pull_request")
    monkeypatch.setenv("CI_REF_TYPE", "branch")
    monkeypatch.setenv("CI_BASE_SHA", "a" * 40)
    monkeypatch.setattr(
        ci_changes.subprocess, "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, stdout=b"README.md\0"),
    )
    ci_changes.main()
    assert output.read_text() == "existing=value\npython=false\ndocker=false\n"


@pytest.mark.parametrize(("event", "ref_type"), [("schedule", "branch"), ("push", "tag")])
def test_releases_and_refreshes_always_run_all_checks(monkeypatch, tmp_path, event, ref_type):
    output = tmp_path / "outputs"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("CI_EVENT_NAME", event)
    monkeypatch.setenv("CI_REF_TYPE", ref_type)
    monkeypatch.setattr(ci_changes, "changed_paths", lambda _: ["README.md"])
    ci_changes.main()
    assert output.read_text() == "python=true\ndocker=true\n"


def test_renaming_runtime_code_to_documentation_still_builds_image(monkeypatch, tmp_path):
    def git(*args):
        return subprocess.run(
            ["git", "-c", "user.name=CI test", "-c", "user.email=ci@example.invalid", *args],
            cwd=tmp_path, check=True, capture_output=True, text=True,
        ).stdout.strip()

    git("init")
    source = tmp_path / "asa_ctrl" / "module.py"
    source.parent.mkdir()
    source.write_text("print('runtime')\n")
    git("add", ".")
    git("commit", "-m", "Initial runtime")
    base = git("rev-parse", "HEAD")
    destination = tmp_path / "docs" / "example.md"
    destination.parent.mkdir()
    source.rename(destination)
    git("add", "-A")
    git("commit", "-m", "Move runtime file into docs")
    monkeypatch.chdir(tmp_path)
    paths = ci_changes.changed_paths(base)
    assert "asa_ctrl/module.py" in paths
    assert ci_changes.required_checks(paths) == (True, True)
