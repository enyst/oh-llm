from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from oh_llm.redaction import Redactor


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _safe_read_text(path: Path, *, max_bytes: int = 50_000) -> str:
    if not path.exists():
        return ""
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    if len(data) > max_bytes:
        data = data[-max_bytes:]
    try:
        return data.decode("utf-8", errors="replace")
    except Exception:
        return ""


def _tail_lines(text: str, *, max_lines: int) -> str:
    lines = (text or "").splitlines()
    if len(lines) <= max_lines:
        return "\n".join(lines).strip()
    return "\n".join(lines[-max_lines:]).strip()


def extract_redact_env(run_record: dict[str, Any]) -> list[str]:
    profile = run_record.get("profile")
    if not isinstance(profile, dict):
        return []
    redact_env = profile.get("redact_env")
    if not isinstance(redact_env, list):
        return []
    names: list[str] = []
    for item in redact_env:
        if isinstance(item, str) and item.strip():
            names.append(item.strip())
    return sorted(set(names))


@dataclass(frozen=True)
class CapsuleArtifacts:
    capsule_json: Path
    capsule_md: Path
    repro_script: Path


def build_capsule(
    *,
    run_dir: Path,
    run_record: dict[str, Any],
    redactor: Redactor,
) -> dict[str, Any]:
    log_path = run_dir / "logs" / "run.log"
    run_log_tail = _tail_lines(_safe_read_text(log_path), max_lines=120)

    stage_b_probe_result_path = run_dir / "artifacts" / "stage_b_probe_result.json"
    stage_b_probe_result = None
    if stage_b_probe_result_path.exists():
        try:
            stage_b_probe_result = json.loads(stage_b_probe_result_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            stage_b_probe_result = None

    capsule: dict[str, Any] = {
        "schema_version": 1,
        "created_at": _utc_now_iso(),
        "run_dir": str(run_dir),
        "run_id": run_record.get("run_id"),
        "profile": run_record.get("profile"),
        "agent_sdk": run_record.get("agent_sdk"),
        "failure": run_record.get("failure"),
        "stages": run_record.get("stages"),
        "log_tail": run_log_tail,
        "stage_b_probe_result": stage_b_probe_result,
        "how_to_repro": {
            "cwd": str(run_dir / "artifacts"),
            "env": {"OH_LLM_AGENT_SDK_PATH": "$HOME/repos/agent-sdk"},
            "commands": [
                "uv --directory \"$OH_LLM_AGENT_SDK_PATH\" run python autofix_repro.py --stage a",
                "uv --directory \"$OH_LLM_AGENT_SDK_PATH\" run python autofix_repro.py --stage b",
            ],
        },
    }

    return redactor.redact_obj(capsule)


def write_capsule_artifacts(
    *,
    run_dir: Path,
    run_record: dict[str, Any],
    redactor: Redactor,
) -> CapsuleArtifacts:
    artifacts_dir = run_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    capsule_json_path = artifacts_dir / "autofix_capsule.json"
    capsule_md_path = artifacts_dir / "autofix_capsule.md"
    repro_script_path = artifacts_dir / "autofix_repro.py"

    capsule = build_capsule(run_dir=run_dir, run_record=run_record, redactor=redactor)
    capsule_json_path.write_text(
        json.dumps(capsule, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    try:
        capsule_json_path.chmod(0o600)
    except OSError:
        pass

    # If a custom repro harness already exists (e.g. for debugging or tests), keep it.
    if not repro_script_path.exists():
        repro_script_path.write_text(
            _repro_script_text(run_dir=run_dir, run_record=run_record),
            encoding="utf-8",
        )
        try:
            repro_script_path.chmod(0o700)
        except OSError:
            pass

    capsule_md_path.write_text(_capsule_md(capsule), encoding="utf-8")
    try:
        capsule_md_path.chmod(0o600)
    except OSError:
        pass

    return CapsuleArtifacts(
        capsule_json=capsule_json_path,
        capsule_md=capsule_md_path,
        repro_script=repro_script_path,
    )


def _repro_script_text(*, run_dir: Path, run_record: dict[str, Any]) -> str:
    # This script is meant to be executed under the agent-sdk uv environment:
    #   uv --directory "$OH_LLM_AGENT_SDK_PATH" run python autofix_repro.py --stage a
    return """#!/usr/bin/env python3
\"\"\"oh-llm auto-fix repro harness (no secrets stored).

Run from this directory (run artifacts):
  uv --directory \"$OH_LLM_AGENT_SDK_PATH\" run python autofix_repro.py --stage a
  uv --directory \"$OH_LLM_AGENT_SDK_PATH\" run python autofix_repro.py --stage b

Notes:
- Reads API keys from the env var name in `stage_a_config.json` / `stage_b_config.json`.
- Does NOT persist secrets to disk.
\"\"\"

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding=\"utf-8\"))


def _error_payload(*, started: float, exc_type: str, message: str, tb: str) -> dict[str, Any]:
    duration_ms = int((time.monotonic() - started) * 1000)
    return {{
        \"ok\": False,
        \"duration_ms\": duration_ms,
        \"error\": {{
            \"type\": exc_type,
            \"message\": message,
        }},
        \"traceback\": tb,
    }}


def _preview(text: str | None, *, max_len: int = 220) -> str | None:
    if text is None:
        return None
    cleaned = str(text).strip().replace(\"\\n\", \" \")
    if not cleaned:
        return None
    return cleaned[:max_len] + (\"…\" if len(cleaned) > max_len else \"\")


def run_stage_a(config_path: Path) -> dict[str, Any]:
    started = time.monotonic()
    config = _read_json(config_path)
    model = str(config.get(\"model\") or \"\").strip()
    base_url = config.get(\"base_url\")
    api_key_env = str(config.get(\"api_key_env\") or \"\").strip()
    timeout_s = int(config.get(\"timeout_s\") or 30)

    api_key = os.environ.get(api_key_env)
    if not api_key:
        return _error_payload(
            started=started,
            exc_type=\"ConfigError\",
            message=f\"API key env var not set: {{api_key_env}}\",
            tb=\"\",
        )

    from openhands.sdk.llm import LLM, Message, TextContent  # type: ignore

    llm = LLM(model=model, base_url=base_url, api_key=api_key, timeout=timeout_s)
    messages = [Message(role=\"user\", content=[TextContent(text=\"Say hello in one word.\")])]
    response = llm.completion(messages, temperature=0, max_tokens=16)

    response_text = \"\"
    for content in response.message.content:
        if getattr(content, \"type\", None) == \"text\":
            response_text = str(getattr(content, \"text\", \"\") or \"\")
            break

    return {{
        \"ok\": True,
        \"duration_ms\": int((time.monotonic() - started) * 1000),
        \"response_preview\": _preview(response_text, max_len=200),
        \"response_id\": getattr(response, \"id\", None),
    }}


def run_stage_b(config_path: Path) -> dict[str, Any]:
    started = time.monotonic()
    config = _read_json(config_path)
    model = str(config.get(\"model\") or \"\").strip()
    base_url = config.get(\"base_url\")
    api_key_env = str(config.get(\"api_key_env\") or \"\").strip()
    timeout_s = int(config.get(\"timeout_s\") or 60)
    max_iterations = int(config.get(\"max_iterations\") or 50)
    workspace_dir = str(config.get(\"workspace_dir\") or \"\").strip()
    terminal_type = config.get(\"terminal_type\")

    api_key = os.environ.get(api_key_env)
    if not api_key:
        return _error_payload(
            started=started,
            exc_type=\"ConfigError\",
            message=f\"API key env var not set: {{api_key_env}}\",
            tb=\"\",
        )

    from openhands.sdk import LLM, Agent, Conversation, Tool  # type: ignore
    from openhands.sdk.event import ActionEvent, MessageEvent, ObservationEvent  # type: ignore
    from openhands.tools.terminal import TerminalTool  # type: ignore

    tool_name = str(TerminalTool.name)
    llm = LLM(model=model, base_url=base_url, api_key=api_key, timeout=timeout_s)

    tool_params: dict[str, Any] = {{}}
    if terminal_type:
        tool_params[\"terminal_type\"] = str(terminal_type)
    tools = [Tool(name=tool_name, params=tool_params)]

    agent = Agent(llm=llm, tools=tools, system_prompt_kwargs={{\"cli_mode\": True}})
    conversation = Conversation(
        agent=agent,
        workspace=workspace_dir,
        max_iteration_per_run=max_iterations,
        stuck_detection=False,
        visualizer=None,
    )

    prompt = \"Run `echo TOOL_OK` in the terminal and then reply with TOOL_OK.\"
    conversation.send_message(prompt)
    conversation.run()

    tool_invoked = False
    tool_observed = False
    tool_output_preview: str | None = None
    tool_command_preview: str | None = None
    final_answer_preview: str | None = None

    for event in conversation.state.events:
        if isinstance(event, ActionEvent) and event.tool_name == tool_name:
            tool_invoked = True
            if tool_command_preview is None:
                cmd = getattr(getattr(event, \"action\", None), \"command\", None)
                tool_command_preview = _preview(cmd)

        if isinstance(event, ObservationEvent) and event.tool_name == tool_name:
            tool_observed = True
            try:
                parts = []
                for chunk in event.observation.to_llm_content:
                    if getattr(chunk, \"type\", None) == \"text\":
                        parts.append(str(getattr(chunk, \"text\", \"\") or \"\"))
                tool_output_preview = _preview(\"\".join(parts), max_len=400)
            except Exception:
                tool_output_preview = None

        if isinstance(event, MessageEvent) and event.llm_message.role == \"assistant\":
            parts = []
            for chunk in event.llm_message.content:
                if getattr(chunk, \"type\", None) == \"text\":
                    parts.append(str(getattr(chunk, \"text\", \"\") or \"\"))
            final_answer_preview = _preview(\"\".join(parts), max_len=220)

    return {{
        \"ok\": True,
        \"duration_ms\": int((time.monotonic() - started) * 1000),
        \"tool_invoked\": tool_invoked,
        \"tool_observed\": tool_observed,
        \"tool_command_preview\": tool_command_preview,
        \"tool_output_preview\": tool_output_preview,
        \"final_answer_preview\": final_answer_preview,
    }}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(\"--stage\", choices=[\"a\", \"b\"], required=True)
    parser.add_argument(\"--artifacts-dir\", default=str(Path(__file__).resolve().parent))
    args = parser.parse_args()

    artifacts_dir = Path(args.artifacts_dir).resolve()
    stage_a_config = artifacts_dir / \"stage_a_config.json\"
    stage_b_config = artifacts_dir / \"stage_b_config.json\"

    try:
        if args.stage == \"a\":
            payload = run_stage_a(stage_a_config)
        else:
            payload = run_stage_b(stage_b_config)
        print(json.dumps(payload, ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001
        started = time.monotonic()
        payload = _error_payload(
            started=started,
            exc_type=type(exc).__name__,
            message=str(exc),
            tb=traceback.format_exc(limit=50),
        )
        print(json.dumps(payload, ensure_ascii=False))
        sys.exit(1)


if __name__ == \"__main__\":
    main()
"""


def _capsule_md(capsule: dict[str, Any]) -> str:
    run_dir = capsule.get("run_dir")
    run_id = capsule.get("run_id")
    failure = capsule.get("failure")
    return (
        "# oh-llm autofix capsule\n\n"
        f"- run_id: `{run_id}`\n"
        f"- run_dir: `{run_dir}`\n"
        f"- failure: `{json.dumps(failure, ensure_ascii=False)}`\n\n"
        "## Log tail\n\n"
        "```text\n"
        + str(capsule.get("log_tail") or "")
        + "\n```\n"
    )
