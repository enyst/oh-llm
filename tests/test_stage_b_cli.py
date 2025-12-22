from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from oh_llm.cli import ExitCode, app
from oh_llm.run_store import read_run_json
from oh_llm.stage_a import StageAOutcome
from oh_llm.stage_b import StageBOutcome

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


def test_stage_b_is_not_run_by_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    _setup_sdk_repo(tmp_path, monkeypatch)
    monkeypatch.setenv("TEST_API_KEY", "not-a-real-key")

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

    def _fake_stage_a(**kwargs: Any) -> StageAOutcome:
        return StageAOutcome(
            ok=True,
            duration_ms=12,
            response_preview="Hello",
            error=None,
            raw={"ok": True, "duration_ms": 12, "response_preview": "Hello"},
        )

    def _should_not_run_stage_b(**kwargs: Any) -> StageBOutcome:
        raise AssertionError("Stage B should not run without --stage-b")

    monkeypatch.setattr("oh_llm.cli.run_stage_a", _fake_stage_a)
    monkeypatch.setattr("oh_llm.cli.run_stage_b", _should_not_run_stage_b)

    result = runner.invoke(
        app,
        ["run", "--profile", "demo", "--runs-dir", str(tmp_path / "runs"), "--json"],
    )
    assert result.exit_code == ExitCode.OK
    payload = json.loads(result.stdout)
    run_dir = Path(payload["run_dir"])
    record = read_run_json(run_dir / "run.json")
    assert record["stages"]["A"]["status"] == "pass"
    assert record["stages"]["B"]["status"] == "not_run"


def test_stage_b_runs_when_enabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    _setup_sdk_repo(tmp_path, monkeypatch)
    monkeypatch.setenv("TEST_API_KEY", "not-a-real-key")

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

    def _fake_stage_a(**kwargs: Any) -> StageAOutcome:
        return StageAOutcome(
            ok=True,
            duration_ms=12,
            response_preview="Hello",
            error=None,
            raw={"ok": True, "duration_ms": 12, "response_preview": "Hello"},
        )

    def _fake_stage_b(**kwargs: Any) -> StageBOutcome:
        return StageBOutcome(
            ok=True,
            duration_ms=34,
            tool_invoked=True,
            tool_observed=True,
            tool_command_preview="echo TOOL_OK",
            tool_output_preview="TOOL_OK",
            final_answer_preview="TOOL_OK",
            error=None,
            raw={"ok": True},
        )

    monkeypatch.setattr("oh_llm.cli.run_stage_a", _fake_stage_a)
    monkeypatch.setattr("oh_llm.cli.run_stage_b", _fake_stage_b)

    result = runner.invoke(
        app,
        [
            "run",
            "--profile",
            "demo",
            "--stage-b",
            "--runs-dir",
            str(tmp_path / "runs"),
            "--json",
        ],
    )
    assert result.exit_code == ExitCode.OK
    payload = json.loads(result.stdout)
    run_dir = Path(payload["run_dir"])
    record = read_run_json(run_dir / "run.json")
    assert record["stages"]["A"]["status"] == "pass"
    assert record["stages"]["B"]["status"] == "pass"
    assert record["stages"]["B"]["result"]["tool_invoked"] is True


def test_invalid_stage_b_terminal_type_fails_fast(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    _setup_sdk_repo(tmp_path, monkeypatch)
    monkeypatch.setenv("TEST_API_KEY", "not-a-real-key")

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

    def _should_not_run_stage_a(**kwargs: Any) -> StageAOutcome:
        raise AssertionError("Stage A should not run when Stage B options are invalid")

    monkeypatch.setattr("oh_llm.cli.run_stage_a", _should_not_run_stage_a)

    result = runner.invoke(
        app,
        [
            "run",
            "--profile",
            "demo",
            "--stage-b",
            "--stage-b-terminal-type",
            "nope",
            "--runs-dir",
            str(tmp_path / "runs"),
            "--json",
        ],
    )
    assert result.exit_code == ExitCode.RUN_FAILED
    payload = json.loads(result.stdout)
    run_dir = Path(payload["run_dir"])
    record = read_run_json(run_dir / "run.json")
    assert record["stages"]["A"]["status"] == "not_run"
    assert record["stages"]["B"]["status"] == "fail"
    assert record["stages"]["B"]["error"]["classification"] == "credential_or_config"


def test_invalid_stage_b_max_iterations_fails_fast(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    _setup_sdk_repo(tmp_path, monkeypatch)
    monkeypatch.setenv("TEST_API_KEY", "not-a-real-key")

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

    def _should_not_run_stage_a(**kwargs: Any) -> StageAOutcome:
        raise AssertionError("Stage A should not run when Stage B options are invalid")

    monkeypatch.setattr("oh_llm.cli.run_stage_a", _should_not_run_stage_a)

    result = runner.invoke(
        app,
        [
            "run",
            "--profile",
            "demo",
            "--stage-b",
            "--stage-b-max-iterations",
            "0",
            "--runs-dir",
            str(tmp_path / "runs"),
            "--json",
        ],
    )
    assert result.exit_code == ExitCode.RUN_FAILED
    payload = json.loads(result.stdout)
    run_dir = Path(payload["run_dir"])
    record = read_run_json(run_dir / "run.json")
    assert record["stages"]["A"]["status"] == "not_run"
    assert record["stages"]["B"]["status"] == "fail"
    assert record["stages"]["B"]["error"]["classification"] == "credential_or_config"
