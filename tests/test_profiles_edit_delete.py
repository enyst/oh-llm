from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from oh_llm.cli import ExitCode, app

pytestmark = pytest.mark.unit


def test_profile_edit_updates_sdk_and_metadata_and_strips_api_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    runner = CliRunner()

    created = runner.invoke(
        app,
        [
            "profile",
            "add",
            "demo",
            "--model",
            "gpt-5-mini",
            "--base-url",
            "https://example.invalid",
            "--api-key-env",
            "DEMO_API_KEY",
        ],
    )
    assert created.exit_code == ExitCode.OK

    sdk_profile = tmp_path / ".openhands" / "llm-profiles" / "demo.json"
    sdk_profile.write_text(
        json.dumps(
            {
                "profile_id": "demo",
                "model": "gpt-5-mini",
                "base_url": "https://example.invalid",
                "api_key": "SUPER_SECRET",
                "extra": {"keep": True},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    edited = runner.invoke(
        app,
        [
            "profile",
            "edit",
            "demo",
            "--model",
            "gemini/gemini-2.0-flash",
            "--base-url",
            "https://example2.invalid",
            "--api-key-env",
            "NEW_KEY_ENV",
            "--json",
        ],
    )
    assert edited.exit_code == ExitCode.OK
    payload = json.loads(edited.stdout)
    assert payload["ok"] is True
    assert payload["profile"]["profile_id"] == "demo"
    assert payload["profile"]["model"] == "gemini/gemini-2.0-flash"
    assert payload["profile"]["base_url"] == "https://example2.invalid"
    assert payload["profile"]["api_key_env"] == "NEW_KEY_ENV"

    sdk_payload = json.loads(sdk_profile.read_text(encoding="utf-8"))
    assert sdk_payload["profile_id"] == "demo"
    assert sdk_payload["model"] == "gemini/gemini-2.0-flash"
    assert sdk_payload["base_url"] == "https://example2.invalid"
    assert "api_key" not in sdk_payload
    assert sdk_payload["extra"] == {"keep": True}

    meta_profile = tmp_path / ".oh-llm" / "profiles" / "demo.json"
    meta_payload = json.loads(meta_profile.read_text(encoding="utf-8"))
    assert meta_payload["api_key_env"] == "NEW_KEY_ENV"


def test_profile_edit_clear_base_url_and_delete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    runner = CliRunner()

    created = runner.invoke(
        app,
        [
            "profile",
            "add",
            "demo",
            "--model",
            "gpt-5-mini",
            "--base-url",
            "https://example.invalid",
            "--api-key-env",
            "DEMO_API_KEY",
        ],
    )
    assert created.exit_code == ExitCode.OK

    cleared = runner.invoke(app, ["profile", "edit", "demo", "--clear-base-url", "--json"])
    assert cleared.exit_code == ExitCode.OK

    sdk_profile = tmp_path / ".openhands" / "llm-profiles" / "demo.json"
    sdk_payload = json.loads(sdk_profile.read_text(encoding="utf-8"))
    assert sdk_payload["model"] == "gpt-5-mini"
    assert "base_url" not in sdk_payload

    deleted = runner.invoke(app, ["profile", "delete", "demo", "--json"])
    assert deleted.exit_code == ExitCode.OK
    deleted_payload = json.loads(deleted.stdout)
    assert deleted_payload["ok"] is True
    assert deleted_payload["deleted"] is True

    assert not (tmp_path / ".openhands" / "llm-profiles" / "demo.json").exists()
    assert not (tmp_path / ".oh-llm" / "profiles" / "demo.json").exists()

    missing_ok = runner.invoke(app, ["profile", "delete", "demo", "--missing-ok", "--json"])
    assert missing_ok.exit_code == ExitCode.OK
    missing_payload = json.loads(missing_ok.stdout)
    assert missing_payload["ok"] is True
    assert missing_payload["deleted"] is False


def test_profile_edit_rejects_conflicting_base_url_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    runner = CliRunner()

    created = runner.invoke(
        app,
        ["profile", "add", "demo", "--model", "gpt-5-mini", "--api-key-env", "DEMO_API_KEY"],
    )
    assert created.exit_code == ExitCode.OK

    result = runner.invoke(
        app,
        ["profile", "edit", "demo", "--base-url", "https://example.invalid", "--clear-base-url"],
    )
    assert result.exit_code == ExitCode.RUN_FAILED
    assert "conflict" in result.stdout.lower()


def test_profile_edit_requires_changes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    runner = CliRunner()

    created = runner.invoke(
        app,
        ["profile", "add", "demo", "--model", "gpt-5-mini", "--api-key-env", "DEMO_API_KEY"],
    )
    assert created.exit_code == ExitCode.OK

    no_changes = runner.invoke(app, ["profile", "edit", "demo", "--json"])
    assert no_changes.exit_code == ExitCode.RUN_FAILED
    payload = json.loads(no_changes.stdout)
    assert payload["ok"] is False
    assert payload["error"] == "no_changes"
