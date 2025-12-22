from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from oh_llm.cli import ExitCode, app
from oh_llm.run_store import read_run_json

pytestmark = pytest.mark.unit


def test_mock_mode_bypasses_api_key_env_requirement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("OH_LLM_AGENT_SDK_PATH", str(tmp_path / "missing-sdk"))

    runner = CliRunner()
    add_profile = runner.invoke(
        app,
        [
            "profile",
            "add",
            "demo",
            "--model",
            "mock-model",
            "--api-key-env",
            "MISSING_API_KEY",
        ],
    )
    assert add_profile.exit_code == ExitCode.OK

    runs_dir = tmp_path / "runs"
    result = runner.invoke(
        app,
        ["run", "--profile", "demo", "--runs-dir", str(runs_dir), "--json", "--mock"],
    )
    assert result.exit_code == ExitCode.OK
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["stages"]["A"]["status"] == "pass"
    assert payload["stages"]["B"]["status"] == "not_run"

    run_dir = Path(payload["run_dir"])
    record = read_run_json(run_dir / "run.json")
    assert record["requested"]["mock"] is True


def test_mock_mode_stage_b_writes_probe_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("OH_LLM_AGENT_SDK_PATH", str(tmp_path / "missing-sdk"))

    runner = CliRunner()
    add_profile = runner.invoke(
        app,
        [
            "profile",
            "add",
            "demo",
            "--model",
            "mock-model",
            "--api-key-env",
            "MISSING_API_KEY",
        ],
    )
    assert add_profile.exit_code == ExitCode.OK

    runs_dir = tmp_path / "runs"
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
            "--mock",
            "--mock-stage-b-mode",
            "compat",
        ],
    )
    assert result.exit_code == ExitCode.OK
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["stages"]["A"]["status"] == "pass"
    assert payload["stages"]["B"]["status"] == "pass"
    assert payload["stages"]["B"]["result"]["tool_invoked"] is True
    assert payload["stages"]["B"]["result"]["tool_observed"] is True

    run_dir = Path(payload["run_dir"])
    probe_result = run_dir / "artifacts" / "stage_b_probe_result.json"
    assert probe_result.exists()
    probe_payload = json.loads(probe_result.read_text(encoding="utf-8"))
    assert probe_payload["mock"] is True
    assert probe_payload["mock_mode"] == "compat"
