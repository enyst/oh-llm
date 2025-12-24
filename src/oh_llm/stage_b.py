from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from oh_llm.agent_sdk import AgentSdkError, agent_sdk_path_problem, uv_run_python
from oh_llm.redaction import Redactor


@dataclass(frozen=True)
class StageBOutcome:
    ok: bool
    duration_ms: int
    tool_invoked: bool
    tool_observed: bool
    tool_command_preview: str | None
    tool_output_preview: str | None
    final_answer_preview: str | None
    error: dict[str, Any] | None
    raw: dict[str, Any]


def _probe_path() -> Path:
    return Path(__file__).parent / "sdk_probes" / "stage_b_probe.py"


def _safe_load_json(text: str) -> dict[str, Any] | None:
    text = (text or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def run_stage_b(
    *,
    agent_sdk_path: Path,
    artifacts_dir: Path,
    model: str,
    base_url: str | None,
    api_key_env: str,
    timeout_s: int,
    max_iterations: int,
    terminal_type: str | None,
    redactor: Redactor,
) -> StageBOutcome:
    problem = agent_sdk_path_problem(agent_sdk_path)
    if problem:
        error = {
            "type": "ConfigError",
            "message": problem,
            "classification": "credential_or_config",
            "hint": "Pass --agent-sdk-path <path> or set $OH_LLM_AGENT_SDK_PATH.",
        }
        return StageBOutcome(
            ok=False,
            duration_ms=0,
            tool_invoked=False,
            tool_observed=False,
            tool_command_preview=None,
            tool_output_preview=None,
            final_answer_preview=None,
            error=error,
            raw={"ok": False, "error": error},
        )

    config_path = artifacts_dir / "stage_b_config.json"
    workspace_dir = artifacts_dir / "stage_b_workspace"
    workspace_dir.mkdir(parents=True, exist_ok=True)

    payload: dict[str, Any] = {
        "model": model,
        "base_url": base_url,
        "api_key_env": api_key_env,
        "timeout_s": timeout_s,
        "max_iterations": max_iterations,
        "workspace_dir": str(workspace_dir),
        "terminal_type": terminal_type,
    }
    config_path.write_text(redactor.redact_json(payload), encoding="utf-8")

    started = time.monotonic()
    try:
        proc = uv_run_python(
            agent_sdk_path=agent_sdk_path,
            python_args=[str(_probe_path()), "--config", str(config_path)],
        )
    except AgentSdkError as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        error = {
            "type": "AgentSdkError",
            "message": str(exc),
            "classification": "credential_or_config",
            "hint": (
                "Ensure `uv` is installed and `OH_LLM_AGENT_SDK_PATH` "
                "points at a valid agent-sdk checkout."
            ),
        }
        return StageBOutcome(
            ok=False,
            duration_ms=duration_ms,
            tool_invoked=False,
            tool_observed=False,
            tool_command_preview=None,
            tool_output_preview=None,
            final_answer_preview=None,
            error=error,
            raw={"ok": False, "error": error},
        )

    duration_ms = int((time.monotonic() - started) * 1000)
    raw = _safe_load_json(proc.stdout) or {}

    probe_payload: dict[str, Any] = raw or {
        "ok": False,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "returncode": proc.returncode,
    }
    probe_result_path = artifacts_dir / "stage_b_probe_result.json"
    probe_result_path.write_text(redactor.redact_json(probe_payload), encoding="utf-8")
    try:
        probe_result_path.chmod(0o600)
    except OSError:
        pass

    if not raw:
        error = {
            "type": "ProbeError",
            "message": "Stage B probe did not return JSON.",
            "classification": "sdk_or_provider_bug",
            "hint": "Inspect logs/run.log and agent-sdk output for details.",
        }
        return StageBOutcome(
            ok=False,
            duration_ms=duration_ms,
            tool_invoked=False,
            tool_observed=False,
            tool_command_preview=None,
            tool_output_preview=None,
            final_answer_preview=None,
            error=error,
            raw={
                "ok": False,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
                "returncode": proc.returncode,
            },
        )

    ok = bool(raw.get("ok"))
    error = raw.get("error")
    if proc.returncode != 0 and ok:
        ok = False
        error = error or {
            "type": "ProbeError",
            "message": f"Probe exited with status {proc.returncode}",
            "classification": "sdk_or_provider_bug",
            "hint": "Inspect agent-sdk stderr for details.",
        }

    return StageBOutcome(
        ok=ok,
        duration_ms=int(raw.get("duration_ms") or duration_ms),
        tool_invoked=bool(raw.get("tool_invoked") or False),
        tool_observed=bool(raw.get("tool_observed") or False),
        tool_command_preview=(
            str(raw.get("tool_command_preview"))
            if raw.get("tool_command_preview") is not None
            else None
        ),
        tool_output_preview=(
            str(raw.get("tool_output_preview"))
            if raw.get("tool_output_preview") is not None
            else None
        ),
        final_answer_preview=(
            str(raw.get("final_answer_preview"))
            if raw.get("final_answer_preview") is not None
            else None
        ),
        error=error if isinstance(error, dict) else None,
        raw=raw,
    )
