from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class AgentSdkError(RuntimeError):
    pass


@dataclass(frozen=True)
class AgentSdkInfo:
    path: Path
    git_sha: str | None
    git_dirty: bool | None
    uv_available: bool

    def as_json(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "exists": self.path.exists(),
            "git_sha": self.git_sha,
            "git_dirty": self.git_dirty,
            "uv_available": self.uv_available,
        }


def resolve_agent_sdk_path(path: Path | None = None) -> Path:
    if path is not None:
        return path.expanduser()

    env_path = os.environ.get("OH_LLM_AGENT_SDK_PATH")
    if env_path:
        return Path(env_path).expanduser()

    return Path("~/repos/agent-sdk").expanduser()


def uv_available() -> bool:
    return shutil.which("uv") is not None


def _run_checked(args: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        args,
        cwd=str(cwd) if cwd is not None else None,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise AgentSdkError(
            "Command failed: "
            + " ".join(args)
            + "\n"
            + (proc.stdout or "")
            + (proc.stderr or "")
        )
    return proc


def get_git_head_sha(repo_path: Path) -> str:
    proc = _run_checked(["git", "-C", str(repo_path), "rev-parse", "HEAD"])
    return proc.stdout.strip()


def is_git_dirty(repo_path: Path) -> bool:
    proc = _run_checked(["git", "-C", str(repo_path), "status", "--porcelain=v1"])
    return bool(proc.stdout.strip())


def collect_agent_sdk_info(repo_path: Path) -> AgentSdkInfo:
    uv_is_available = uv_available()
    if not repo_path.exists():
        return AgentSdkInfo(
            path=repo_path,
            git_sha=None,
            git_dirty=None,
            uv_available=uv_is_available,
        )

    git_sha: str | None = None
    git_dirty: bool | None = None
    try:
        git_sha = get_git_head_sha(repo_path)
        git_dirty = is_git_dirty(repo_path)
    except AgentSdkError:
        pass

    return AgentSdkInfo(
        path=repo_path,
        git_sha=git_sha,
        git_dirty=git_dirty,
        uv_available=uv_is_available,
    )


def uv_run_python(
    *,
    agent_sdk_path: Path,
    python_args: list[str],
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    if not uv_available():
        raise AgentSdkError("`uv` not found on PATH; required to run agent-sdk workspace.")

    merged_env = dict(os.environ)
    merged_env.pop("VIRTUAL_ENV", None)
    if env:
        merged_env.update(env)

    return subprocess.run(
        ["uv", "--directory", str(agent_sdk_path), "run", "python", *python_args],
        env=merged_env,
        capture_output=True,
        text=True,
        check=False,
    )
