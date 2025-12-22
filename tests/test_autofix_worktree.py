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


def _setup_sdk_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    sdk_repo = tmp_path / "agent-sdk"
    sdk_repo.mkdir()
    _git(sdk_repo, "init")
    (sdk_repo / "README.md").write_text("sdk\n", encoding="utf-8")
    _git_commit(sdk_repo, message="init")
    monkeypatch.setenv("OH_LLM_AGENT_SDK_PATH", str(sdk_repo))
    return sdk_repo


def _write_run(runs_dir: Path, *, dirname: str, run_id: str, profile_name: str) -> Path:
    run_dir = runs_dir / dirname
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_id": run_id,
                "created_at": "2025-01-02T00:00:00+00:00",
                "profile": {"name": profile_name},
                "agent_sdk": {"path": "/tmp/agent-sdk", "git_sha": None, "git_dirty": None},
                "host": {
                    "hostname": "test",
                    "platform": "test",
                    "python": "3.12.0",
                    "executable": "python",
                },
                "stages": {
                    "A": {"status": "fail"},
                    "B": {"status": "not_run"},
                    "C": {"status": "not_run"},
                },
                "failure": {"classification": "sdk_or_provider_bug"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return run_dir


def test_autofix_worktree_creates_and_cleans_up_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    sdk_repo = _setup_sdk_repo(tmp_path, monkeypatch)

    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    run_dir = _write_run(
        runs_dir,
        dirname="20250102_000000_demo_abcd",
        run_id="run_abc123",
        profile_name="demo",
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "autofix",
            "worktree",
            "--run",
            run_dir.name,
            "--runs-dir",
            str(runs_dir),
            "--json",
        ],
    )
    assert result.exit_code == ExitCode.OK
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    record = payload["worktree"]
    branch = record["worktree"]["branch"]
    worktree_path = Path(record["worktree"]["path"])
    assert record["worktree"]["cleaned_up"] is True
    assert not worktree_path.exists()

    worktree_record_path = run_dir / "artifacts" / "autofix_worktree.json"
    assert worktree_record_path.exists()

    branches = _git(sdk_repo, "branch", "--list", branch).stdout.strip().splitlines()
    assert branches == []


def test_autofix_worktree_refuses_dirty_sdk_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    sdk_repo = _setup_sdk_repo(tmp_path, monkeypatch)
    (sdk_repo / "DIRTY.txt").write_text("dirty\n", encoding="utf-8")

    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    run_dir = _write_run(
        runs_dir,
        dirname="20250102_000000_demo_efgh",
        run_id="run_def456",
        profile_name="demo",
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "autofix",
            "worktree",
            "--run",
            run_dir.name,
            "--runs-dir",
            str(runs_dir),
            "--json",
        ],
    )
    assert result.exit_code == ExitCode.RUN_FAILED
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert "dirty agent-sdk checkout" in payload["error"]
