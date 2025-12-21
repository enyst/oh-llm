from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from oh_llm.agent_sdk import get_git_head_sha, is_git_dirty, resolve_agent_sdk_path


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


def test_resolve_agent_sdk_path_prefers_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("OH_LLM_AGENT_SDK_PATH", str(tmp_path))
    assert resolve_agent_sdk_path() == tmp_path


def test_git_sha_and_dirty_detection(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")

    (repo / "a.txt").write_text("hello\n", encoding="utf-8")
    _git_commit(repo, message="init")

    sha = get_git_head_sha(repo)
    assert re.fullmatch(r"[0-9a-f]{40}", sha)
    assert is_git_dirty(repo) is False

    (repo / "a.txt").write_text("changed\n", encoding="utf-8")
    assert is_git_dirty(repo) is True
