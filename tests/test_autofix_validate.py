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


def _write_run(
    runs_dir: Path,
    *,
    dirname: str,
    run_id: str,
    profile_name: str,
    secret_env: str,
) -> Path:
    run_dir = runs_dir / dirname
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    (run_dir / "logs").mkdir(parents=True, exist_ok=True)
    (run_dir / "logs" / "run.log").write_text("log\n", encoding="utf-8")
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_id": run_id,
                "created_at": "2025-01-02T00:00:00+00:00",
                "profile": {"name": profile_name, "redact_env": [secret_env]},
                "agent_sdk": {"path": "/tmp/agent-sdk", "git_sha": None, "git_dirty": None},
                "host": {
                    "hostname": "test",
                    "platform": "test",
                    "python": "3.12.0",
                    "executable": "python",
                },
                "stages": {
                    "A": {"status": "fail"},
                    "B": {"status": "fail"},
                    "C": {"status": "not_run"},
                },
                "failure": {"classification": "sdk_or_provider_bug"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return run_dir


def _write_repro_script(
    artifacts_dir: Path,
    *,
    secret_value: str,
    stage_b_ok: bool,
) -> Path:
    script_path = artifacts_dir / "autofix_repro.py"
    script_path.write_text(
        (
            "#!/usr/bin/env python3\n"
            "from __future__ import annotations\n"
            "import argparse, json, sys\n"
            "p=argparse.ArgumentParser(); p.add_argument('--stage', required=True)\n"
            "args=p.parse_args()\n"
            "if args.stage == 'a':\n"
            f"    print(json.dumps({{'ok': True, 'note': 'secret={secret_value}'}}))\n"
            "    sys.exit(0)\n"
            f"ok = {stage_b_ok}\n"
            f"print(json.dumps({{'ok': ok, 'note': 'secret={secret_value}'}}))\n"
            "sys.exit(0 if ok else 1)\n"
        ),
        encoding="utf-8",
    )
    script_path.chmod(0o700)
    return script_path


def test_autofix_validate_runs_repro_and_redacts_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    _setup_sdk_repo(tmp_path, monkeypatch)

    secret_env = "TEST_SECRET_ENV"
    secret_value = "super-secret-value"
    monkeypatch.setenv(secret_env, secret_value)

    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    run_dir = _write_run(
        runs_dir,
        dirname="20250102_000000_demo_abcd",
        run_id="run_abc123",
        profile_name="demo",
        secret_env=secret_env,
    )
    _write_repro_script(run_dir / "artifacts", secret_value=secret_value, stage_b_ok=True)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "autofix",
            "validate",
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

    stage_a_text = Path(payload["artifacts"]["stage_a"]).read_text(encoding="utf-8")
    stage_b_text = Path(payload["artifacts"]["stage_b"]).read_text(encoding="utf-8")

    assert secret_value not in stage_a_text
    assert secret_value not in stage_b_text
    assert "<REDACTED>" in stage_a_text


def test_autofix_validate_fails_when_stage_b_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    _setup_sdk_repo(tmp_path, monkeypatch)

    secret_env = "TEST_SECRET_ENV"
    monkeypatch.setenv(secret_env, "super-secret-value")

    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    run_dir = _write_run(
        runs_dir,
        dirname="20250102_000000_demo_fail",
        run_id="run_fail123",
        profile_name="demo",
        secret_env=secret_env,
    )
    _write_repro_script(run_dir / "artifacts", secret_value="super-secret-value", stage_b_ok=False)

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["autofix", "validate", "--run", run_dir.name, "--runs-dir", str(runs_dir), "--json"],
    )
    assert result.exit_code == ExitCode.RUN_FAILED
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
