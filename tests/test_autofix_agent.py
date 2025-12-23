from __future__ import annotations

import json
import os
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


def _write_fake_openhands(tmp_path: Path, *, secret_value: str) -> Path:
    # This simulates `openhands` and prints a secret to stdout; the caller must redact it.
    path = tmp_path / "fake_openhands.py"
    path.write_text(
        (
            "#!/usr/bin/env python3\n"
            "import sys\n"
            f"print('hello {secret_value}')\n"
            "print('Authorization: Bearer sk-THIS_SHOULD_BE_REDACTED')\n"
            "print('args=' + ' '.join(sys.argv[1:]))\n"
        ),
        encoding="utf-8",
    )
    os.chmod(path, 0o700)
    return path


def test_autofix_agent_runs_openhands_and_redacts_transcript(
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

    fake_openhands = _write_fake_openhands(tmp_path, secret_value=secret_value)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "autofix",
            "agent",
            "--run",
            run_dir.name,
            "--runs-dir",
            str(runs_dir),
            "--openhands-bin",
            str(fake_openhands),
            "--json",
        ],
    )
    assert result.exit_code == ExitCode.OK
    payload = json.loads(result.stdout)
    assert payload["ok"] is True

    artifacts = payload["artifacts"]
    transcript = Path(artifacts["transcript_log"])
    diff_patch = Path(artifacts["diff_patch"])
    context_md = Path(artifacts["context_md"])

    assert transcript.exists()
    assert diff_patch.exists()
    assert context_md.exists()

    transcript_text = transcript.read_text(encoding="utf-8")
    assert secret_value not in transcript_text
    assert "<REDACTED>" in transcript_text
