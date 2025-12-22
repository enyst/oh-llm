from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from oh_llm.cli import ExitCode, app

pytestmark = pytest.mark.unit


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )


def _git_commit(repo: Path, *, message: str) -> None:
    _git(repo, "add", "-A")
    _git(
        repo,
        "-c",
        "user.name=oh-llm",
        "-c",
        "user.email=oh-llm@example.invalid",
        "commit",
        "-m",
        message,
    )


def _setup_sdk_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sdk_repo = tmp_path / "agent-sdk"
    sdk_repo.mkdir()
    _git(sdk_repo, "init")
    (sdk_repo / "README.md").write_text("sdk\n", encoding="utf-8")
    _git_commit(sdk_repo, message="init")
    monkeypatch.setenv("OH_LLM_AGENT_SDK_PATH", str(sdk_repo))


def test_autofix_refuses_credential_or_config_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    _setup_sdk_repo(tmp_path, monkeypatch)

    runner = CliRunner()
    add_profile = runner.invoke(
        app,
        [
            "profile",
            "add",
            "demo",
            "--model",
            "gpt-5-mini",
            "--api-key-env",
            "MISSING_API_KEY",
        ],
    )
    assert add_profile.exit_code == ExitCode.OK

    runs_dir = tmp_path / "runs"
    result = runner.invoke(
        app, ["run", "--profile", "demo", "--runs-dir", str(runs_dir), "--json"]
    )
    assert result.exit_code == ExitCode.RUN_FAILED
    run_payload = json.loads(result.stdout)
    run_dir = Path(run_payload["run_dir"])

    autofix = runner.invoke(
        app,
        [
            "autofix",
            "start",
            "--run",
            run_dir.name,
            "--runs-dir",
            str(runs_dir),
            "--json",
        ],
    )
    assert autofix.exit_code == ExitCode.RUN_FAILED
    payload = json.loads(autofix.stdout)
    assert payload["ok"] is False
    assert payload["error"] == "refused"
    assert payload["reason"] == "credential_or_config"


def test_autofix_force_bypasses_gating_but_is_stub(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    _setup_sdk_repo(tmp_path, monkeypatch)

    runner = CliRunner()
    add_profile = runner.invoke(
        app,
        [
            "profile",
            "add",
            "demo",
            "--model",
            "gpt-5-mini",
            "--api-key-env",
            "MISSING_API_KEY",
        ],
    )
    assert add_profile.exit_code == ExitCode.OK

    runs_dir = tmp_path / "runs"
    result = runner.invoke(
        app, ["run", "--profile", "demo", "--runs-dir", str(runs_dir), "--json"]
    )
    assert result.exit_code == ExitCode.RUN_FAILED
    run_dir = Path(json.loads(result.stdout)["run_dir"])

    autofix = runner.invoke(
        app,
        [
            "autofix",
            "start",
            "--run",
            run_dir.name,
            "--runs-dir",
            str(runs_dir),
            "--force",
            "--json",
        ],
    )
    assert autofix.exit_code == ExitCode.INTERNAL_ERROR
    payload = json.loads(autofix.stdout)
    assert payload["ok"] is False
    assert payload["error"] == "not_implemented"
    assert payload["failure"]["classification"] == "credential_or_config"
