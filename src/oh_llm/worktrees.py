from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from oh_llm.agent_sdk import AgentSdkError, get_git_head_sha, is_git_dirty

_BRANCH_SAFE = re.compile(r"[^a-z0-9-]+")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _slug(value: str) -> str:
    cleaned = _BRANCH_SAFE.sub("-", (value or "").strip().lower()).strip("-")
    return cleaned or "unknown"


def _run_git(repo: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise AgentSdkError(
            "Command failed: git -C "
            + str(repo)
            + " "
            + " ".join(args)
            + "\n"
            + (proc.stdout or "")
            + (proc.stderr or "")
        )
    return proc


@dataclass(frozen=True)
class WorktreeRecord:
    schema_version: int
    created_at: str
    agent_sdk_path: str
    agent_sdk_base_sha: str
    agent_sdk_dirty: bool
    worktree_path: str
    branch: str
    keep_worktree: bool
    cleaned_up: bool

    def as_json(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "created_at": self.created_at,
            "agent_sdk": {
                "path": self.agent_sdk_path,
                "base_sha": self.agent_sdk_base_sha,
                "dirty": self.agent_sdk_dirty,
            },
            "worktree": {
                "path": self.worktree_path,
                "branch": self.branch,
                "keep_worktree": self.keep_worktree,
                "cleaned_up": self.cleaned_up,
            },
        }


def derive_branch_name(*, profile_name: str, run_id: str) -> str:
    # Keep short enough to be readable and safe for git.
    return f"oh-llm-autofix-{_slug(profile_name)}-{_slug(run_id)[:16]}"


def create_sdk_worktree(
    *,
    agent_sdk_path: Path,
    worktree_path: Path,
    profile_name: str,
    run_id: str,
    allow_dirty: bool,
    keep_worktree: bool,
) -> WorktreeRecord:
    if not agent_sdk_path.exists():
        raise AgentSdkError(f"agent-sdk path does not exist: {agent_sdk_path}")

    base_sha = get_git_head_sha(agent_sdk_path)
    dirty = is_git_dirty(agent_sdk_path)
    if dirty and not allow_dirty:
        raise AgentSdkError(
            "Refusing to create an auto-fix worktree from a dirty agent-sdk checkout. "
            "Commit/stash changes in the agent-sdk repo, or pass --allow-dirty-sdk."
        )

    branch = derive_branch_name(profile_name=profile_name, run_id=run_id)

    worktree_path.parent.mkdir(parents=True, exist_ok=True)
    if worktree_path.exists():
        raise AgentSdkError(f"Worktree path already exists: {worktree_path}")

    _run_git(
        agent_sdk_path,
        ["worktree", "add", "-b", branch, str(worktree_path), base_sha],
    )

    return WorktreeRecord(
        schema_version=1,
        created_at=_utc_now_iso(),
        agent_sdk_path=str(agent_sdk_path),
        agent_sdk_base_sha=base_sha,
        agent_sdk_dirty=dirty,
        worktree_path=str(worktree_path),
        branch=branch,
        keep_worktree=keep_worktree,
        cleaned_up=False,
    )


def cleanup_sdk_worktree(
    *, agent_sdk_path: Path, worktree_path: Path, branch: str
) -> None:
    # Remove worktree checkout.
    _run_git(agent_sdk_path, ["worktree", "remove", "--force", str(worktree_path)])
    # Best-effort branch cleanup (branch may not exist / may already be deleted).
    try:
        _run_git(agent_sdk_path, ["branch", "-D", branch])
    except AgentSdkError:
        pass


def mark_worktree_cleaned(record: WorktreeRecord) -> WorktreeRecord:
    return replace(record, cleaned_up=True)


def write_worktree_record(path: Path, *, record: WorktreeRecord) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(record.as_json(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    try:
        path.chmod(0o600)
    except OSError:
        pass
