from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from oh_llm import __version__
from oh_llm.cli import ExitCode, app
from oh_llm.redaction import REDACTED, redactor_from_env_vars
from oh_llm.run_store import (
    append_log,
    build_run_record,
    create_run_dir,
    default_stage_template,
    read_run_json,
    write_run_json,
)
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


def test_write_run_json_redacts_secret_values_and_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SECRET_ENV", "supersecret")
    redactor = redactor_from_env_vars("SECRET_ENV")

    run_json = tmp_path / "run.json"
    run_record = {
        "schema_version": 1,
        "profile": {"api_key": "supersecret", "token": "t0k3n", "api_key_env": "SECRET_ENV"},
        "stages": {"A": {"status": "not_run", "duration_ms": None}},
    }
    write_run_json(path=run_json, run_record=run_record, redactor=redactor)

    contents = run_json.read_text(encoding="utf-8")
    assert "supersecret" not in contents
    assert "t0k3n" not in contents
    assert REDACTED in contents


def test_append_log_redacts_secret_values(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECRET_ENV", "supersecret")
    redactor = redactor_from_env_vars("SECRET_ENV")

    log_file = tmp_path / "logs" / "run.log"
    append_log(
        path=log_file,
        message="Authorization: Bearer sk-aaaaaaaaaaaaaaaaaaaaaaaaaaaa supersecret",
        redactor=redactor,
    )

    contents = log_file.read_text(encoding="utf-8")
    assert "supersecret" not in contents
    assert "sk-aaaaaaaaaaaaaaaaaaaaaaaaaaaa" not in contents
    assert REDACTED in contents
    if os.name == "posix":
        assert (log_file.stat().st_mode & 0o777) == 0o600


def test_cli_run_creates_run_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    # Create a deterministic, local "agent-sdk" git repo so the run.json can capture a SHA.
    sdk_repo = tmp_path / "agent-sdk"
    sdk_repo.mkdir()
    _git(sdk_repo, "init")
    (sdk_repo / "README.md").write_text("sdk\n", encoding="utf-8")
    _git_commit(sdk_repo, message="init")
    sha = _git(sdk_repo, "rev-parse", "HEAD").stdout.strip()

    monkeypatch.setenv("OH_LLM_AGENT_SDK_PATH", str(sdk_repo))
    monkeypatch.setenv("TEST_API_KEY", "not-a-real-key")

    runner = CliRunner()
    add_profile = runner.invoke(
        app,
        [
            "profile",
            "add",
            "test_profile",
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

    monkeypatch.setattr("oh_llm.cli.run_stage_a", _fake_stage_a)

    runs_dir = tmp_path / "runs"
    result = runner.invoke(
        app,
        [
            "run",
            "--profile",
            "test_profile",
            "--runs-dir",
            str(runs_dir),
            "--json",
        ],
    )
    assert result.exit_code == ExitCode.OK

    payload = json.loads(result.stdout)
    run_dir = Path(payload["run_dir"])
    assert run_dir.exists()
    assert (run_dir / "run.json").exists()
    assert (run_dir / "logs" / "run.log").exists()
    assert (run_dir / "artifacts").exists()

    record = read_run_json(run_dir / "run.json")
    assert record["schema_version"] == 1
    assert record["oh_llm"]["version"] == __version__
    assert re.fullmatch(r"[0-9a-f]{40}", record["oh_llm"]["git_sha"] or "")
    assert record["oh_llm"]["git_dirty"] in {True, False}
    assert record["agent_sdk"]["git_sha"] == sha
    assert set(record["stages"].keys()) >= {"A", "B"}
    assert record["stages"]["A"]["status"] == "pass"

    run_json_text = (run_dir / "run.json").read_text(encoding="utf-8")
    assert "not-a-real-key" not in run_json_text


def test_create_run_dir_naming(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    run = create_run_dir(runs_dir=runs_dir, profile_name="My Profile")
    assert run.run_dir.exists()
    assert "_My_Profile_" in run.run_dir.name
    assert run.run_id in run.run_dir.name


def test_build_run_record_has_expected_top_level_keys(tmp_path: Path) -> None:
    record = build_run_record(
        run_id="abc123",
        created_at="2025-01-01T00:00:00+00:00",
        profile={"name": "demo"},
        agent_sdk=_AgentSdkInfoLike(path=tmp_path),
        stages=default_stage_template(),
    )

    assert record["schema_version"] == 1
    assert record["run_id"] == "abc123"
    assert record["created_at"]
    assert "profile" in record
    assert "agent_sdk" in record
    assert "host" in record
    assert "stages" in record
    assert set(record["stages"].keys()) >= {"A", "B", "C"}


class _AgentSdkInfoLike:
    def __init__(self, *, path: Path) -> None:
        self.path = path
        self.git_sha = None
        self.git_dirty = None
