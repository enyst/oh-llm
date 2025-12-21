from __future__ import annotations

import json
from pathlib import Path

import pytest

from oh_llm.redaction import REDACTED, redactor_from_env_vars
from oh_llm.run_store import write_run_json

pytestmark = pytest.mark.unit


def test_write_run_json_redacts_nested_stage_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SECRET_ENV", "supersecret")
    redactor = redactor_from_env_vars("SECRET_ENV")

    run_json = tmp_path / "run.json"
    record = {
        "schema_version": 1,
        "run_id": "abc123",
        "created_at": "2025-01-01T00:00:00+00:00",
        "profile": {"api_key_env": "SECRET_ENV"},
        "agent_sdk": {"path": "/tmp/sdk", "git_sha": None, "git_dirty": None},
        "host": {"hostname": "host"},
        "stages": {
            "A": {
                "name": "connectivity + basic completion",
                "status": "fail",
                "duration_ms": 10,
                "error": {
                    "type": "ProviderError",
                    "message": "401 Unauthorized: supersecret",
                    "classification": "credential_or_config",
                    "hint": "Check Authorization: Bearer sk-aaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                },
            }
        },
    }
    write_run_json(path=run_json, run_record=record, redactor=redactor)

    contents = run_json.read_text(encoding="utf-8")
    assert "supersecret" not in contents
    assert "sk-aaaaaaaaaaaaaaaaaaaaaaaaaaaa" not in contents
    assert REDACTED in contents


def test_write_run_json_redacts_secret_key_names(tmp_path: Path) -> None:
    redactor = redactor_from_env_vars()

    run_json = tmp_path / "run.json"
    record = {
        "schema_version": 1,
        "profile": {"token": "should-not-appear", "api_key": "also-should-not-appear"},
        "stages": {},
    }
    write_run_json(path=run_json, run_record=record, redactor=redactor)

    payload = json.loads(run_json.read_text(encoding="utf-8"))
    assert payload["profile"]["token"] == REDACTED
    assert payload["profile"]["api_key"] == REDACTED
