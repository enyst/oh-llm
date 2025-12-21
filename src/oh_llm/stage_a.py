from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from oh_llm.agent_sdk import AgentSdkError, uv_run_python
from oh_llm.redaction import Redactor


@dataclass(frozen=True)
class StageAOutcome:
    ok: bool
    duration_ms: int
    response_preview: str | None
    error: dict[str, Any] | None
    raw: dict[str, Any]


def _probe_path() -> Path:
    return Path(__file__).parent / "sdk_probes" / "stage_a_probe.py"


def _safe_load_json(text: str) -> dict[str, Any] | None:
    text = (text or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def run_stage_a(
    *,
    agent_sdk_path: Path,
    artifacts_dir: Path,
    model: str,
    base_url: str | None,
    api_key_env: str,
    timeout_s: int,
    redactor: Redactor,
) -> StageAOutcome:
    config_path = artifacts_dir / "stage_a_config.json"
    payload: dict[str, Any] = {
        "model": model,
        "base_url": base_url,
        "api_key_env": api_key_env,
        "timeout_s": timeout_s,
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
        return StageAOutcome(
            ok=False,
            duration_ms=duration_ms,
            response_preview=None,
            error=error,
            raw={"ok": False, "error": error},
        )

    duration_ms = int((time.monotonic() - started) * 1000)
    raw = _safe_load_json(proc.stdout) or {}

    if not raw:
        error = {
            "type": "ProbeError",
            "message": "Stage A probe did not return JSON.",
            "classification": "sdk_or_provider_bug",
            "hint": "Inspect logs/run.log and agent-sdk output for details.",
        }
        return StageAOutcome(
            ok=False,
            duration_ms=duration_ms,
            response_preview=None,
            error=error,
            raw={
                "ok": False,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
                "returncode": proc.returncode,
            },
        )

    ok = bool(raw.get("ok"))
    response_preview = raw.get("response_preview")
    error = raw.get("error")
    if proc.returncode != 0 and ok:
        ok = False
        error = error or {
            "type": "ProbeError",
            "message": f"Probe exited with status {proc.returncode}",
            "classification": "sdk_or_provider_bug",
            "hint": "Inspect agent-sdk stderr for details.",
        }

    return StageAOutcome(
        ok=ok,
        duration_ms=int(raw.get("duration_ms") or duration_ms),
        response_preview=str(response_preview) if response_preview is not None else None,
        error=error if isinstance(error, dict) else None,
        raw=raw,
    )
