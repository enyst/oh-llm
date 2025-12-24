from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from shutil import which

import pytest


@pytest.fixture(autouse=True)
def _require_uv() -> None:
    if which("uv") is None:
        pytest.skip("uv not available")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _json_line(stdout: str) -> dict:
    text = (stdout or "").strip()
    assert text
    return json.loads(text.splitlines()[-1])


def test_provider_smoke_help() -> None:
    proc = subprocess.run(
        ["uv", "run", "python", "scripts/provider_smoke.py", "--help"],
        cwd=str(_repo_root()),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout


def test_provider_smoke_fails_fast_when_env_missing(tmp_path: Path) -> None:
    env = dict(os.environ)
    env.pop("OPENAI_API_KEY", None)

    proc = subprocess.run(
        [
            "uv",
            "run",
            "python",
            "scripts/provider_smoke.py",
            "--provider",
            "openai",
            "--model",
            "openai/gpt-4o-mini",
            "--home-dir",
            str(tmp_path / "home"),
            "--json",
        ],
        cwd=str(_repo_root()),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode != 0
    assert "OPENAI_API_KEY" in (proc.stderr or proc.stdout)


def test_provider_smoke_mock_offline_openai(tmp_path: Path) -> None:
    env = dict(os.environ)
    env["OPENAI_API_KEY"] = "test-secret"
    env["OH_LLM_AGENT_SDK_PATH"] = str(tmp_path / "agent-sdk")
    (tmp_path / "agent-sdk").mkdir(parents=True, exist_ok=True)

    proc = subprocess.run(
        [
            "uv",
            "run",
            "python",
            "scripts/provider_smoke.py",
            "--provider",
            "openai",
            "--model",
            "openai/gpt-4o-mini",
            "--home-dir",
            str(tmp_path / "home"),
            "--mock",
            "--stage-b",
            "--json",
        ],
        cwd=str(_repo_root()),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    payload = _json_line(proc.stdout)
    assert payload["ok"] is True
    assert payload["provider"] == "openai"
    assert payload["run_dir"]
