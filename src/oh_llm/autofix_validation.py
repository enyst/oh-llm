from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from oh_llm.agent_sdk import uv_run_python
from oh_llm.redaction import Redactor


@dataclass(frozen=True)
class CommandResult:
    command: list[str]
    exit_code: int
    duration_ms: int
    stdout: str
    stderr: str

    def as_json(self) -> dict[str, Any]:
        return {
            "command": list(self.command),
            "exit_code": self.exit_code,
            "duration_ms": self.duration_ms,
            "stdout": self.stdout,
            "stderr": self.stderr,
        }


def run_repro_stage(
    *,
    worktree_path: Path,
    repro_script_path: Path,
    stage: str,
) -> CommandResult:
    started = time.monotonic()
    proc = uv_run_python(
        agent_sdk_path=worktree_path,
        python_args=[str(repro_script_path), "--stage", stage],
    )
    duration_ms = int((time.monotonic() - started) * 1000)
    return CommandResult(
        command=[
            "uv",
            "--directory",
            str(worktree_path),
            "run",
            "python",
            str(repro_script_path),
            "--stage",
            stage,
        ],
        exit_code=int(proc.returncode),
        duration_ms=duration_ms,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
    )


def parse_json_stdout(result: CommandResult) -> dict[str, Any] | None:
    text = (result.stdout or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def write_validation_artifact(
    *,
    path: Path,
    payload: dict[str, Any],
    redactor: Redactor,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(redactor.redact_obj(payload), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    try:
        path.chmod(0o600)
    except OSError:
        pass
