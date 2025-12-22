from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from oh_llm.cli import ExitCode, app

pytestmark = pytest.mark.unit


def _write_run(runs_dir: Path, *, dirname: str) -> Path:
    run_dir = runs_dir / dirname
    (run_dir / "artifacts").mkdir(parents=True, exist_ok=False)
    (run_dir / "logs").mkdir(parents=True, exist_ok=True)
    return run_dir


def test_autofix_capsule_redacts_secrets_from_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    secret_env = "TEST_SECRET_ENV"
    secret_value = "super-secret-value"
    monkeypatch.setenv(secret_env, secret_value)

    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    run_dir = _write_run(runs_dir, dirname="20250102_000000_demo_abcd")

    run_record = {
        "schema_version": 1,
        "run_id": "run_abc123",
        "created_at": "2025-01-02T00:00:00+00:00",
        "profile": {
            "name": "demo",
            "redact_env": [secret_env],
            "resolved": {"api_key_env": secret_env},
        },
        "agent_sdk": {"path": "/tmp/agent-sdk", "git_sha": "deadbeef", "git_dirty": False},
        "host": {
            "hostname": "test",
            "platform": "test",
            "python": "3.12.0",
            "executable": "python",
        },
        "stages": {"A": {"status": "fail"}, "B": {"status": "fail"}, "C": {"status": "not_run"}},
        "failure": {"classification": "sdk_or_provider_bug"},
    }
    (run_dir / "run.json").write_text(json.dumps(run_record) + "\n", encoding="utf-8")

    (run_dir / "logs" / "run.log").write_text(
        f"Something failed: {secret_value}\n", encoding="utf-8"
    )
    (run_dir / "artifacts" / "stage_b_probe_result.json").write_text(
        json.dumps({"ok": False, "error": {"message": f"bad token: {secret_value}"}}) + "\n",
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["autofix", "capsule", "--run", run_dir.name, "--runs-dir", str(runs_dir), "--json"],
    )
    assert result.exit_code == ExitCode.OK
    payload = json.loads(result.stdout)
    artifacts = payload["artifacts"]

    capsule_json_path = Path(artifacts["capsule_json"])
    capsule_md_path = Path(artifacts["capsule_md"])
    repro_path = Path(artifacts["repro_script"])

    capsule_json_text = capsule_json_path.read_text(encoding="utf-8")
    capsule_md_text = capsule_md_path.read_text(encoding="utf-8")
    repro_text = repro_path.read_text(encoding="utf-8")

    assert secret_value not in capsule_json_text
    assert secret_value not in capsule_md_text
    assert secret_value not in repro_text

    assert "<REDACTED>" in capsule_json_text
