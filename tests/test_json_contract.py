from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from oh_llm.cli import ExitCode, app
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


def _setup_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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


def _fake_stage_a(**_kwargs: Any) -> StageAOutcome:
    return StageAOutcome(
        ok=True,
        duration_ms=12,
        response_preview="Hello",
        error=None,
        raw={"ok": True, "duration_ms": 12, "response_preview": "Hello"},
    )


def test_run_json_contract_stage_a_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_profile(tmp_path, monkeypatch)
    monkeypatch.setattr("oh_llm.cli.run_stage_a", _fake_stage_a)

    runs_dir = tmp_path / "runs"
    runner = CliRunner()
    result = runner.invoke(app, ["run", "--profile", "demo", "--runs-dir", str(runs_dir), "--json"])
    assert result.exit_code == ExitCode.OK

    payload = json.loads(result.stdout)
    assert set(payload.keys()) == {"failure", "ok", "run_dir", "stages"}
    assert payload["ok"] is True
    assert payload["failure"] is None
    assert payload["stages"]["A"]["status"] == "pass"
    assert payload["stages"]["B"]["status"] == "not_run"


def test_run_json_contract_stage_b_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_profile(tmp_path, monkeypatch)
    monkeypatch.setattr("oh_llm.cli.run_stage_a", _fake_stage_a)

    def _fake_stage_b(**_kwargs: Any) -> StageBOutcome:
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

    monkeypatch.setattr("oh_llm.cli.run_stage_b", _fake_stage_b)

    runs_dir = tmp_path / "runs"
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "run",
            "--profile",
            "demo",
            "--runs-dir",
            str(runs_dir),
            "--json",
            "--stage-b",
        ],
    )
    assert result.exit_code == ExitCode.OK

    payload = json.loads(result.stdout)
    assert set(payload.keys()) == {"failure", "ok", "run_dir", "stages"}
    assert payload["ok"] is True
    assert payload["failure"] is None
    assert payload["stages"]["A"]["status"] == "pass"
    assert payload["stages"]["B"]["status"] == "pass"


def test_run_json_contract_exit_code_on_stage_b_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_profile(tmp_path, monkeypatch)
    monkeypatch.setattr("oh_llm.cli.run_stage_a", _fake_stage_a)

    def _fake_stage_b(**_kwargs: Any) -> StageBOutcome:
        return StageBOutcome(
            ok=False,
            duration_ms=34,
            tool_invoked=False,
            tool_observed=False,
            tool_command_preview=None,
            tool_output_preview=None,
            final_answer_preview=None,
            error={
                "classification": "sdk_or_provider_bug",
                "type": "ProbeError",
                "message": "Stage B failed.",
                "hint": "Inspect run artifacts for details.",
            },
            raw={"ok": False},
        )

    monkeypatch.setattr("oh_llm.cli.run_stage_b", _fake_stage_b)

    runs_dir = tmp_path / "runs"
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "run",
            "--profile",
            "demo",
            "--runs-dir",
            str(runs_dir),
            "--json",
            "--stage-b",
        ],
    )
    assert result.exit_code == ExitCode.RUN_FAILED

    payload = json.loads(result.stdout)
    assert set(payload.keys()) == {"failure", "ok", "run_dir", "stages"}
    assert payload["ok"] is False
    assert payload["failure"]["classification"] == "sdk_or_provider_bug"
    assert payload["stages"]["B"]["status"] == "fail"


def _write_run(runs_dir: Path, *, dirname: str, run_id: str, created_at: str, stages: dict) -> None:
    run_dir = runs_dir / dirname
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_id": run_id,
                "created_at": created_at,
                "profile": {"name": "demo"},
                "agent_sdk": {"path": "/tmp/agent-sdk", "git_sha": None, "git_dirty": None},
                "host": {
                    "hostname": "test",
                    "platform": "test",
                    "python": "3.12.0",
                    "executable": "python",
                },
                "stages": stages,
            }
        ),
        encoding="utf-8",
    )


def test_runs_list_show_json_contract(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()

    _write_run(
        runs_dir,
        dirname="20250102_000000_demo_bbbb",
        run_id="bbbb2222cccc",
        created_at="2025-01-02T00:00:00+00:00",
        stages={"A": {"status": "pass"}, "B": {"status": "pass"}, "C": {"status": "not_run"}},
    )

    runner = CliRunner()
    listed = runner.invoke(app, ["runs", "list", "--runs-dir", str(runs_dir), "--json"])
    assert listed.exit_code == ExitCode.OK
    payload = json.loads(listed.stdout)
    assert set(payload.keys()) == {"runs"}
    assert len(payload["runs"]) == 1
    assert set(payload["runs"][0].keys()) == {
        "created_at",
        "profile_name",
        "run_dir",
        "run_id",
        "stages",
        "status",
    }

    shown = runner.invoke(
        app, ["runs", "show", "bbbb2222cccc", "--runs-dir", str(runs_dir), "--json"]
    )
    assert shown.exit_code == ExitCode.OK
    shown_payload = json.loads(shown.stdout)
    assert set(shown_payload.keys()) == {"ok", "run", "run_dir"}
    assert shown_payload["ok"] is True
    assert shown_payload["run"]["run_id"] == "bbbb2222cccc"
