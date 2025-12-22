from __future__ import annotations

import json
import os
import platform
import socket
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from oh_llm import __version__
from oh_llm.agent_sdk import AgentSdkError, AgentSdkInfo, get_git_head_sha, is_git_dirty
from oh_llm.redaction import Redactor


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def resolve_runs_dir() -> Path:
    env = os.environ.get("OH_LLM_RUNS_DIR")
    if env:
        return Path(env).expanduser()
    return Path("~/.oh-llm/runs").expanduser()


def _slug(value: str) -> str:
    cleaned = []
    for ch in value.strip():
        if ch.isalnum() or ch in {"-", "_"}:
            cleaned.append(ch)
        elif ch.isspace():
            cleaned.append("_")
    slug = "".join(cleaned).strip("_")
    return slug[:40] if slug else "unknown"


def _new_run_id() -> str:
    return uuid.uuid4().hex[:12]


def default_stage_template() -> dict[str, Any]:
    return {
        "A": {"name": "connectivity + basic completion", "status": "not_run", "duration_ms": None},
        "B": {
            "name": "end-to-end agent run (tool calling)",
            "status": "not_run",
            "duration_ms": None,
        },
        "C": {"name": "optional advanced gates", "status": "not_run", "duration_ms": None},
    }


@dataclass(frozen=True)
class RunPaths:
    run_dir: Path
    run_id: str
    created_at: str
    run_json: Path
    logs_dir: Path
    log_file: Path
    artifacts_dir: Path


def create_run_dir(*, runs_dir: Path, profile_name: str | None) -> RunPaths:
    runs_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc).replace(microsecond=0)
    created_at = now.isoformat()
    timestamp = now.strftime("%Y%m%d_%H%M%S")
    run_id = _new_run_id()
    suffix = _slug(profile_name or "unknown")
    name = f"{timestamp}_{suffix}_{run_id}"

    run_dir = runs_dir / name
    run_dir.mkdir(parents=True, exist_ok=False)

    logs_dir = run_dir / "logs"
    logs_dir.mkdir()

    artifacts_dir = run_dir / "artifacts"
    artifacts_dir.mkdir()

    return RunPaths(
        run_dir=run_dir,
        run_id=run_id,
        created_at=created_at,
        run_json=run_dir / "run.json",
        logs_dir=logs_dir,
        log_file=logs_dir / "run.log",
        artifacts_dir=artifacts_dir,
    )


def collect_host_info() -> dict[str, Any]:
    return {
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "executable": sys.executable,
    }


def collect_oh_llm_info() -> dict[str, Any]:
    info: dict[str, Any] = {"version": __version__}
    try:
        repo_root = Path(__file__).resolve().parents[2]
        info["git_sha"] = get_git_head_sha(repo_root)
        info["git_dirty"] = is_git_dirty(repo_root)
    except (OSError, AgentSdkError, IndexError):
        info["git_sha"] = None
        info["git_dirty"] = None
    return info


def build_run_record(
    *,
    run_id: str,
    created_at: str,
    profile: dict[str, Any],
    agent_sdk: AgentSdkInfo,
    stages: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "run_id": run_id,
        "created_at": created_at,
        "oh_llm": collect_oh_llm_info(),
        "profile": profile,
        "agent_sdk": {
            "path": str(agent_sdk.path),
            "git_sha": agent_sdk.git_sha,
            "git_dirty": agent_sdk.git_dirty,
        },
        "host": collect_host_info(),
        "stages": stages,
    }


def write_run_json(*, path: Path, run_record: dict[str, Any], redactor: Redactor) -> None:
    path.write_text(redactor.redact_json(run_record), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def append_log(*, path: Path, message: str, redactor: Redactor) -> None:
    line = f"[{_utc_now_iso()}] {message}\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(redactor.redact_text(line))
    try:
        path.chmod(0o600)
    except OSError:
        pass


def read_run_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
