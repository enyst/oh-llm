from __future__ import annotations

import argparse
import json
import os
import time
import traceback
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _classify_error(*, exc_type: str, message: str) -> tuple[str, str]:
    text = f"{exc_type}: {message}".lower()

    credential_markers = [
        "unauthorized",
        "invalid api key",
        "api key invalid",
        "incorrect api key",
        "missing api key",
        "no api key",
        "authentication",
        "forbidden",
        "401",
        "403",
    ]
    if any(marker in text for marker in credential_markers):
        return (
            "credential_or_config",
            "Check your API key env var and provider credentials.",
        )

    model_markers = ["model_not_found", "no such model", "does not exist", "404"]
    if any(marker in text for marker in model_markers):
        return ("credential_or_config", "Check that the model name is correct.")

    network_markers = [
        "api connection error",
        "connection refused",
        "name or service not known",
        "nodename nor servname provided",
        "timed out",
        "timeout",
        "ssl",
    ]
    if any(marker in text for marker in network_markers):
        return ("credential_or_config", "Check base_url/network connectivity and timeout.")

    return (
        "sdk_or_provider_bug",
        "Likely SDK/provider incompatibility; inspect tool events and logs.",
    )


def _success_payload(
    *,
    started: float,
    tool_invoked: bool,
    tool_observed: bool,
    final_answer_preview: str | None,
    tool_output_preview: str | None,
) -> dict[str, Any]:
    duration_ms = int((time.monotonic() - started) * 1000)
    return {
        "ok": True,
        "duration_ms": duration_ms,
        "tool_invoked": tool_invoked,
        "tool_observed": tool_observed,
        "final_answer_preview": final_answer_preview,
        "tool_output_preview": tool_output_preview,
    }


def _error_payload(*, started: float, exc_type: str, message: str, tb: str) -> dict[str, Any]:
    duration_ms = int((time.monotonic() - started) * 1000)
    classification, hint = _classify_error(exc_type=exc_type, message=message)
    return {
        "ok": False,
        "duration_ms": duration_ms,
        "tool_invoked": False,
        "tool_observed": False,
        "final_answer_preview": None,
        "error": {
            "type": exc_type,
            "message": message,
            "classification": classification,
            "hint": hint,
        },
        "traceback": tb,
    }


def _preview(text: str | None, *, max_len: int = 220) -> str | None:
    if text is None:
        return None
    cleaned = str(text).strip().replace("\n", " ")
    if not cleaned:
        return None
    return cleaned[:max_len] + ("…" if len(cleaned) > max_len else "")


def _tool_name() -> str:
    # ToolDefinition names in agent-sdk are snake_case ("terminal"), not class names.
    from openhands.tools.terminal import TerminalTool  # noqa: PLC0415

    return str(TerminalTool.name)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, help="Path to stage-b config json.")
    args = parser.parse_args()

    started = time.monotonic()

    try:
        config = _read_json(Path(args.config))

        model = str(config.get("model") or "").strip()
        base_url = config.get("base_url")
        api_key_env = str(config.get("api_key_env") or "").strip()
        timeout_s = int(config.get("timeout_s") or 30)
        max_iterations = int(config.get("max_iterations") or 50)
        workspace_dir = str(config.get("workspace_dir") or "").strip()
        terminal_type = config.get("terminal_type")

        if not model:
            payload = _error_payload(
                started=started,
                exc_type="ConfigError",
                message="Missing required field: model",
                tb="",
            )
            print(json.dumps(payload, ensure_ascii=False))
            return

        if not api_key_env:
            payload = _error_payload(
                started=started,
                exc_type="ConfigError",
                message="Missing required field: api_key_env",
                tb="",
            )
            print(json.dumps(payload, ensure_ascii=False))
            return

        if not workspace_dir:
            payload = _error_payload(
                started=started,
                exc_type="ConfigError",
                message="Missing required field: workspace_dir",
                tb="",
            )
            print(json.dumps(payload, ensure_ascii=False))
            return

        api_key = os.environ.get(api_key_env)
        if not api_key:
            payload = _error_payload(
                started=started,
                exc_type="ConfigError",
                message=f"API key env var not set: {api_key_env}",
                tb="",
            )
            print(json.dumps(payload, ensure_ascii=False))
            return

        from openhands.sdk import LLM, Agent, Conversation, Tool  # noqa: PLC0415
        from openhands.sdk.event import (  # noqa: PLC0415
            ActionEvent,
            MessageEvent,
            ObservationEvent,
        )

        # Importing the tool module registers it into the tool registry.
        tool_name = _tool_name()

        llm = LLM(model=model, base_url=base_url, api_key=api_key, timeout=timeout_s)

        tool_params: dict[str, Any] = {}
        if terminal_type:
            tool_params["terminal_type"] = str(terminal_type)

        tools = [Tool(name=tool_name, params=tool_params)]
        agent = Agent(llm=llm, tools=tools, system_prompt_kwargs={"cli_mode": True})
        conversation = Conversation(
            agent=agent,
            workspace=workspace_dir,
            max_iteration_per_run=max_iterations,
            stuck_detection=False,
            visualizer=None,
        )

        prompt = "Run `echo TOOL_OK` in the terminal and then reply with TOOL_OK."
        conversation.send_message(prompt)
        conversation.run()

        tool_invoked = False
        tool_observed = False
        tool_output_preview: str | None = None
        final_answer_preview: str | None = None

        for event in conversation.state.events:
            if isinstance(event, ActionEvent) and event.tool_name == tool_name:
                tool_invoked = True

            if isinstance(event, ObservationEvent) and event.tool_name == tool_name:
                tool_observed = True
                try:
                    parts = []
                    for chunk in event.observation.to_llm_content:
                        if getattr(chunk, "type", None) == "text":
                            parts.append(str(getattr(chunk, "text", "") or ""))
                    tool_output_preview = _preview("".join(parts), max_len=400)
                except Exception:
                    tool_output_preview = None

            if isinstance(event, MessageEvent) and event.llm_message.role == "assistant":
                parts = []
                for chunk in event.llm_message.content:
                    if getattr(chunk, "type", None) == "text":
                        parts.append(str(getattr(chunk, "text", "") or ""))
                final_answer_preview = _preview("".join(parts), max_len=220)

        if not tool_invoked:
            payload = _error_payload(
                started=started,
                exc_type="ToolCallError",
                message="No terminal tool call was invoked during Stage B.",
                tb="",
            )
            print(json.dumps(payload, ensure_ascii=False))
            return

        if not final_answer_preview or "TOOL_OK" not in final_answer_preview:
            payload = _error_payload(
                started=started,
                exc_type="AssertionError",
                message="Agent did not produce final answer containing TOOL_OK.",
                tb="",
            )
            print(json.dumps(payload, ensure_ascii=False))
            return

        payload = _success_payload(
            started=started,
            tool_invoked=tool_invoked,
            tool_observed=tool_observed,
            final_answer_preview=final_answer_preview,
            tool_output_preview=tool_output_preview,
        )
        print(json.dumps(payload, ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001
        payload = _error_payload(
            started=started,
            exc_type=type(exc).__name__,
            message=str(exc),
            tb=traceback.format_exc(limit=50),
        )
        print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
