from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from oh_llm.cli import ExitCode, app

pytestmark = pytest.mark.unit


def _write_run(runs_dir: Path, *, dirname: str, run_id: str, created_at: str, stages: dict) -> Path:
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
    return run_dir


def test_runs_list_empty_when_dir_missing(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["runs", "list", "--runs-dir", str(tmp_path / "missing"), "--json"],
    )
    assert result.exit_code == ExitCode.OK
    payload = json.loads(result.stdout)
    assert payload == {"runs": []}


def test_runs_list_and_show(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()

    _write_run(
        runs_dir,
        dirname="20250101_000000_demo_aaaa",
        run_id="aaaa1111bbbb",
        created_at="2025-01-01T00:00:00+00:00",
        stages={"A": {"status": "pass"}, "B": {"status": "not_run"}, "C": {"status": "not_run"}},
    )
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
    assert payload["runs"][0]["run_id"] == "bbbb2222cccc"
    assert payload["runs"][0]["status"] == "partial"
    assert payload["runs"][0]["stages"]["B"] == "pass"

    shown = runner.invoke(
        app,
        ["runs", "show", "bbbb2222cccc", "--runs-dir", str(runs_dir), "--json"],
    )
    assert shown.exit_code == ExitCode.OK
    shown_payload = json.loads(shown.stdout)
    assert shown_payload["ok"] is True
    assert shown_payload["run"]["run_id"] == "bbbb2222cccc"


def test_runs_show_ambiguous_prefix(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()

    _write_run(
        runs_dir,
        dirname="20250101_000000_demo_aaaa",
        run_id="abc1111bbbb",
        created_at="2025-01-01T00:00:00+00:00",
        stages={"A": {"status": "pass"}},
    )
    _write_run(
        runs_dir,
        dirname="20250102_000000_demo_bbbb",
        run_id="abc2222cccc",
        created_at="2025-01-02T00:00:00+00:00",
        stages={"A": {"status": "pass"}},
    )

    runner = CliRunner()
    result = runner.invoke(app, ["runs", "show", "abc", "--runs-dir", str(runs_dir), "--json"])
    assert result.exit_code == ExitCode.RUN_FAILED
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert "ambiguous" in payload["error"].lower()
