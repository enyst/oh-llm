from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from oh_llm.cli import ExitCode, app
from oh_llm.run_store import read_run_json

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


def test_run_stage_a_fails_fast_when_api_key_env_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    # Create a deterministic, local "agent-sdk" git repo so the run.json can capture a SHA.
    sdk_repo = tmp_path / "agent-sdk"
    sdk_repo.mkdir()
    _git(sdk_repo, "init")
    (sdk_repo / "README.md").write_text("sdk\n", encoding="utf-8")
    _git_commit(sdk_repo, message="init")
    monkeypatch.setenv("OH_LLM_AGENT_SDK_PATH", str(sdk_repo))

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

    result = runner.invoke(
        app,
        [
            "run",
            "--profile",
            "demo",
            "--runs-dir",
            str(tmp_path / "runs"),
            "--json",
        ],
    )
    assert result.exit_code == ExitCode.RUN_FAILED
    payload = json.loads(result.stdout)
    run_dir = Path(payload["run_dir"])
    record = read_run_json(run_dir / "run.json")
    assert record["stages"]["A"]["status"] == "fail"
    assert record["stages"]["A"]["error"]["classification"] == "credential_or_config"
    assert record["failure"]["classification"] == "credential_or_config"
    assert payload["failure"]["classification"] == "credential_or_config"
