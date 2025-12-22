from __future__ import annotations

from typing import Any


def _as_str(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    return None


def classify_text(*, exc_type: str | None, message: str | None) -> tuple[str, str]:
    text = f"{exc_type or ''}: {message or ''}".lower()

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
        "Likely SDK/provider incompatibility; inspect run artifacts/logs.",
    )


def failure_from_stages(stages: dict[str, Any]) -> dict[str, Any] | None:
    """Compute an overall failure classification from per-stage statuses/errors.

    Returns `None` when no stage is marked as failed.
    """

    if not isinstance(stages, dict):
        return None

    for stage_key in ["A", "B", "C"]:
        stage = stages.get(stage_key)
        if not isinstance(stage, dict):
            continue
        if stage.get("status") != "fail":
            continue

        error = stage.get("error") if isinstance(stage.get("error"), dict) else {}
        exc_type = _as_str(error.get("type"))
        message = _as_str(error.get("message"))
        hint = _as_str(error.get("hint"))

        classification = _as_str(error.get("classification"))
        if not classification:
            classification, auto_hint = classify_text(exc_type=exc_type, message=message)
            hint = hint or auto_hint

        return {
            "classification": classification,
            "stage": stage_key,
            "type": exc_type,
            "message": message,
            "hint": hint,
        }

    return None


def update_run_failure(run_record: dict[str, Any]) -> None:
    """Update `run_record["failure"]` in-place based on stage outcomes."""

    if not isinstance(run_record, dict):
        return
    stages = run_record.get("stages")
    failure = failure_from_stages(stages if isinstance(stages, dict) else {})
    if failure is None:
        run_record.pop("failure", None)
    else:
        run_record["failure"] = failure

