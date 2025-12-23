from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from oh_llm.cli import ExitCode, app

pytestmark = pytest.mark.unit


def _write_minimal_run(*, run_dir: Path, failure: dict) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "run_id": "test-run",
        "created_at": "2025-01-01T00:00:00+00:00",
        "profile": {"name": "demo", "model": "demo-model", "resolved": {"model": "demo-model"}},
        "stages": {},
        "failure": failure,
    }
    (run_dir / "run.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def test_autofix_refuses_credential_or_config_by_default(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    run_dir = runs_dir / "20250101_000000_demo_deadbeef"
    _write_minimal_run(
        run_dir=run_dir,
        failure={"classification": "credential_or_config", "summary": "401 Unauthorized"},
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["autofix", "--run", run_dir.name, "--runs-dir", str(runs_dir)],
    )
    assert result.exit_code == ExitCode.RUN_FAILED
    assert "refusing" in result.stdout.lower()
    assert "credential" in result.stdout.lower()


def test_autofix_force_reaches_openhands_resolution_before_sdk(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    run_dir = runs_dir / "20250101_000000_demo_deadbeef"
    _write_minimal_run(
        run_dir=run_dir,
        failure={"classification": "sdk_bug", "summary": "boom"},
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "autofix",
            "--run",
            run_dir.name,
            "--runs-dir",
            str(runs_dir),
            "--force",
            "--openhands-bin",
            "this-openhands-bin-does-not-exist",
        ],
    )
    assert result.exit_code == ExitCode.RUN_FAILED
    assert "openhands" in result.stdout.lower()
