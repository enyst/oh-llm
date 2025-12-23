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
    return json.loads(path.read_text(encoding="utf-8"))


def _ensure_oh_llm_importable() -> None:
    # Probes are executed as standalone scripts; make `src/` importable for shared helpers.
    src_dir = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(src_dir))


_ensure_oh_llm_importable()
from oh_llm.failures import classify_text  # noqa: E402
from oh_llm.prompts import stage_a_user_prompt  # noqa: E402


def _prompt() -> str:
    return stage_a_user_prompt()


def _success_payload(
    *, started: float, response_text: str, response_id: str | None
) -> dict[str, Any]:
    duration_ms = int((time.monotonic() - started) * 1000)
    preview = response_text.strip().replace("\n", " ")
    if len(preview) > 200:
        preview = preview[:200] + "…"
    return {
        "ok": True,
        "duration_ms": duration_ms,
        "response_id": response_id,
        "response_preview": preview,
    }


def _error_payload(*, started: float, exc_type: str, message: str, tb: str) -> dict[str, Any]:
    duration_ms = int((time.monotonic() - started) * 1000)
    classification, hint = classify_text(exc_type=exc_type, message=message)
    return {
        "ok": False,
        "duration_ms": duration_ms,
        "error": {
            "type": exc_type,
            "message": message,
            "classification": classification,
            "hint": hint,
        },
        "traceback": tb,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, help="Path to stage-a config json.")
    args = parser.parse_args()

    started = time.monotonic()

    try:
        config = _read_json(Path(args.config))

        model = str(config.get("model") or "").strip()
        base_url = config.get("base_url")
        api_key_env = str(config.get("api_key_env") or "").strip()
        timeout_s = int(config.get("timeout_s") or 30)

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

        from openhands.sdk.llm import LLM, Message, TextContent  # noqa: PLC0415

        llm = LLM(model=model, base_url=base_url, api_key=api_key, timeout=timeout_s)
        messages = [
            Message(
                role="user",
                content=[TextContent(text=_prompt())],
            )
        ]
        response = llm.completion(messages, temperature=0, max_tokens=16)

        response_text = ""
        for content in response.message.content:
            if getattr(content, "type", None) == "text":
                response_text = str(getattr(content, "text", "") or "")
                break

        if not response_text.strip():
            payload = _error_payload(
                started=started,
                exc_type="ResponseError",
                message="LLM returned an empty response.",
                tb="",
            )
            print(json.dumps(payload, ensure_ascii=False))
            return

        payload = _success_payload(
            started=started,
            response_text=response_text,
            response_id=getattr(response, "id", None),
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
