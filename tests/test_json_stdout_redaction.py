from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from oh_llm.cli import ExitCode, app
from oh_llm.stage_a import StageAOutcome

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


def test_cli_json_stdout_is_redacted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    _setup_sdk_repo(tmp_path, monkeypatch)

    secret = "supersecret"
    monkeypatch.setenv("TEST_API_KEY", secret)

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
            "TEST_API_KEY",
        ],
    )
    assert add_profile.exit_code == ExitCode.OK

    def _fake_stage_a(**_kwargs: Any) -> StageAOutcome:
        return StageAOutcome(
            ok=False,
            duration_ms=12,
            response_preview=None,
            error={
                "classification": "sdk_or_provider_bug",
                "type": "ProbeError",
                "message": f"boom {secret}",
                "hint": "n/a",
            },
            raw={"ok": False},
        )

    monkeypatch.setattr("oh_llm.cli.run_stage_a", _fake_stage_a)

    runs_dir = tmp_path / "runs"
    result = runner.invoke(
        app,
        ["run", "--profile", "demo", "--runs-dir", str(runs_dir), "--json"],
    )
    assert result.exit_code == ExitCode.RUN_FAILED
    assert secret not in result.stdout
    assert "<REDACTED>" in result.stdout

    payload = json.loads(result.stdout)
    assert payload["stages"]["A"]["error"]["message"] == "boom <REDACTED>"

