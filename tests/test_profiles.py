from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from oh_llm.cli import ExitCode, app

pytestmark = pytest.mark.unit


def test_profile_add_list_show_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    runner = CliRunner()
    result = runner.invoke(
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
    assert result.exit_code == ExitCode.OK

    sdk_profile = tmp_path / ".openhands" / "llm-profiles" / "demo.json"
    meta_profile = tmp_path / ".oh-llm" / "profiles" / "demo.json"
    assert sdk_profile.exists()
    assert meta_profile.exists()

    sdk_payload = json.loads(sdk_profile.read_text(encoding="utf-8"))
    assert sdk_payload["profile_id"] == "demo"
    assert sdk_payload["model"] == "gpt-5-mini"
    assert sdk_payload["base_url"] == "https://example.invalid"
    assert "api_key" not in sdk_payload

    meta_payload = json.loads(meta_profile.read_text(encoding="utf-8"))
    assert meta_payload["profile_id"] == "demo"
    assert meta_payload["api_key_env"] == "DEMO_API_KEY"

    show = runner.invoke(app, ["profile", "show", "demo", "--json"])
    assert show.exit_code == ExitCode.OK
    show_payload = json.loads(show.stdout)
    assert show_payload["ok"] is True
    assert show_payload["profile"]["profile_id"] == "demo"
    assert show_payload["profile"]["api_key_env"] == "DEMO_API_KEY"

    list_result = runner.invoke(app, ["profile", "list", "--json"])
    assert list_result.exit_code == ExitCode.OK
    list_payload = json.loads(list_result.stdout)
    assert [p["profile_id"] for p in list_payload["profiles"]] == ["demo"]


def test_profile_add_requires_safe_inputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    runner = CliRunner()

    bad_id = runner.invoke(
        app,
        [
            "profile",
            "add",
            "bad/id",
            "--model",
            "gpt-5-mini",
            "--api-key-env",
            "DEMO_API_KEY",
        ],
    )
    assert bad_id.exit_code == ExitCode.RUN_FAILED

    bad_env = runner.invoke(
        app,
        [
            "profile",
            "add",
            "demo",
            "--model",
            "gpt-5-mini",
            "--api-key-env",
            "BAD-ENV",
        ],
    )
    assert bad_env.exit_code == ExitCode.RUN_FAILED


def test_profile_add_overwrite_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    runner = CliRunner()

    first = runner.invoke(
        app,
        ["profile", "add", "demo", "--model", "gpt-5-mini", "--api-key-env", "DEMO_API_KEY"],
    )
    assert first.exit_code == ExitCode.OK

    second = runner.invoke(
        app,
        ["profile", "add", "demo", "--model", "gpt-5-mini", "--api-key-env", "DEMO_API_KEY"],
    )
    assert second.exit_code == ExitCode.RUN_FAILED

    third = runner.invoke(
        app,
        [
            "profile",
            "add",
            "demo",
            "--model",
            "gpt-5-mini",
            "--api-key-env",
            "DEMO_API_KEY",
            "--overwrite",
        ],
    )
    assert third.exit_code == ExitCode.OK

