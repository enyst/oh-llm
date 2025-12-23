from __future__ import annotations

import json
import re
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


def test_sdk_status_missing_path(tmp_path: Path) -> None:
    runner = CliRunner()
    missing = tmp_path / "missing-sdk"
    result = runner.invoke(app, ["sdk", "status", "--path", str(missing), "--json"])
    assert result.exit_code == ExitCode.RUN_FAILED
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"] == "missing_path"
    assert payload["sdk_path"] == str(missing)


def test_sdk_status_not_git_repo(tmp_path: Path) -> None:
    runner = CliRunner()
    path = tmp_path / "not-git"
    path.mkdir()
    result = runner.invoke(app, ["sdk", "status", "--path", str(path), "--json"])
    assert result.exit_code == ExitCode.RUN_FAILED
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"] == "not_git_repo"
    assert payload["sdk_path"] == str(path)


def test_sdk_status_ok_and_dirty_detection(tmp_path: Path) -> None:
    runner = CliRunner()
    repo = tmp_path / "agent-sdk"
    repo.mkdir()
    _git(repo, "init")

    (repo / "a.txt").write_text("hello\n", encoding="utf-8")
    _git_commit(repo, message="init")

    clean = runner.invoke(app, ["sdk", "status", "--path", str(repo), "--json"])
    assert clean.exit_code == ExitCode.OK
    clean_payload = json.loads(clean.stdout)
    assert clean_payload["ok"] is True
    assert clean_payload["sdk_path"] == str(repo)
    assert re.fullmatch(r"[0-9a-f]{40}", clean_payload["git_sha"] or "")
    assert clean_payload["dirty"] is False

    (repo / "a.txt").write_text("changed\n", encoding="utf-8")
    dirty = runner.invoke(app, ["sdk", "status", "--path", str(repo), "--json"])
    assert dirty.exit_code == ExitCode.OK
    dirty_payload = json.loads(dirty.stdout)
    assert dirty_payload["ok"] is True
    assert dirty_payload["dirty"] is True

