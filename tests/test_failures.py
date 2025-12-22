from __future__ import annotations

import pytest

from oh_llm.failures import classify_text, failure_from_stages

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("exc_type", "message"),
    [
        ("AuthenticationError", "Unauthorized (401)"),
        ("ValueError", "Invalid API key"),
        ("PermissionError", "Forbidden (403)"),
        ("ConnectionError", "Connection refused"),
        ("TimeoutError", "Timed out"),
        ("NotFoundError", "model_not_found"),
    ],
)
def test_classify_text_config_like(exc_type: str, message: str) -> None:
    classification, _hint = classify_text(exc_type=exc_type, message=message)
    assert classification == "credential_or_config"


def test_classify_text_defaults_to_sdk_bug() -> None:
    classification, _hint = classify_text(exc_type="WeirdError", message="Something unexpected")
    assert classification == "sdk_or_provider_bug"


def test_failure_from_stages_picks_first_failed_stage() -> None:
    failure = failure_from_stages(
        {
            "A": {"status": "fail", "error": {"classification": "credential_or_config"}},
            "B": {"status": "fail", "error": {"classification": "sdk_or_provider_bug"}},
        }
    )
    assert failure is not None
    assert failure["stage"] == "A"
    assert failure["classification"] == "credential_or_config"

