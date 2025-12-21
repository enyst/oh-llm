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


def test_profile_show_not_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    runner = CliRunner()
    result = runner.invoke(app, ["profile", "show", "missing"])
    assert result.exit_code == ExitCode.RUN_FAILED
    assert "not found" in result.stdout.lower()


def test_profile_list_includes_sdk_only_and_metadata_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    # SDK-only profile
    sdk_dir = tmp_path / ".openhands" / "llm-profiles"
    sdk_dir.mkdir(parents=True)
    (sdk_dir / "sdk_only.json").write_text(
        json.dumps({"profile_id": "sdk_only", "model": "gpt-5-mini"}, indent=2) + "\n",
        encoding="utf-8",
    )

    # metadata-only profile
    meta_dir = tmp_path / ".oh-llm" / "profiles"
    meta_dir.mkdir(parents=True)
    (meta_dir / "meta_only.json").write_text(
        json.dumps(
            {"schema_version": 1, "profile_id": "meta_only", "api_key_env": "KEY_ENV"},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(app, ["profile", "list", "--json"])
    assert result.exit_code == ExitCode.OK
    payload = json.loads(result.stdout)
    ids = [p["profile_id"] for p in payload["profiles"]]
    assert ids == ["meta_only", "sdk_only"]

    meta_only = next(p for p in payload["profiles"] if p["profile_id"] == "meta_only")
    assert meta_only["model"] is None
    assert meta_only["api_key_env"] == "KEY_ENV"

    sdk_only = next(p for p in payload["profiles"] if p["profile_id"] == "sdk_only")
    assert sdk_only["model"] == "gpt-5-mini"
    assert sdk_only["api_key_env"] is None


def test_profile_list_ignores_invalid_ids(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    sdk_dir = tmp_path / ".openhands" / "llm-profiles"
    sdk_dir.mkdir(parents=True)
    (sdk_dir / "bad id.json").write_text(
        json.dumps({"profile_id": "bad id", "model": "gpt-5-mini"}, indent=2) + "\n",
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(app, ["profile", "list", "--json"])
    assert result.exit_code == ExitCode.OK
    payload = json.loads(result.stdout)
    assert payload["profiles"] == []
