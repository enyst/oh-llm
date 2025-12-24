from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from shutil import which

import pytest

pytestmark = pytest.mark.e2e


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _run_oh_llm(
    *,
    env: dict[str, str],
    args: list[str],
    cwd: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["uv", "run", "oh-llm", *args],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _json_line(proc: subprocess.CompletedProcess[str]) -> dict:
    text = (proc.stdout or "").strip()
    assert text, proc.stderr or proc.stdout
    return json.loads(text.splitlines()[-1])


def _run_json(
    *,
    env: dict[str, str],
    args: list[str],
    cwd: Path,
    expected_returncode: int,
) -> dict:
    proc = _run_oh_llm(env=env, args=args, cwd=cwd)
    assert proc.returncode == expected_returncode, proc.stderr or proc.stdout
    return _json_line(proc)


def test_cli_smoke_offline_mock_mode_and_missing_key(tmp_path: Path) -> None:
    if which("uv") is None:
        pytest.skip("uv not available")

    repo_root = _repo_root()
    profile_name = "demo"

    # Minimal directory for uv `--directory` execution (probe returns before importing SDK).
    sdk_path = tmp_path / "agent-sdk"
    sdk_path.mkdir()

    env = dict(os.environ)
    env["HOME"] = str(tmp_path)
    env["OH_LLM_AGENT_SDK_PATH"] = str(sdk_path)

    help_proc = _run_oh_llm(env=env, args=["--help"], cwd=repo_root)
    assert help_proc.returncode == 0, help_proc.stderr or help_proc.stdout

    add_profile_payload = _run_json(
        env=env,
        args=[
            "profile",
            "add",
            profile_name,
            "--model",
            "mock-model",
            "--api-key-env",
            "MISSING_API_KEY",
            "--json",
        ],
        cwd=repo_root,
        expected_returncode=0,
    )
    assert add_profile_payload["ok"] is True

    runs_dir = tmp_path / "runs"
    base_run_args = ["run", "--profile", profile_name, "--runs-dir", str(runs_dir), "--json"]

    # Negative test: non-mock run should fail fast as credential/config without network calls.
    run_non_mock = _run_oh_llm(env=env, args=base_run_args, cwd=repo_root)
    assert run_non_mock.returncode != 0
    non_mock_payload = _json_line(run_non_mock)
    assert non_mock_payload["ok"] is False
    assert non_mock_payload["failure"]["classification"] == "credential_or_config"

    # Mock Stage A-only.
    mock_a_payload = _run_json(
        env=env,
        args=[*base_run_args, "--mock"],
        cwd=repo_root,
        expected_returncode=0,
    )
    assert mock_a_payload["ok"] is True
    assert mock_a_payload["stages"]["A"]["status"] == "pass"

    # Mock Stage B in both modes (native + compat).
    native_payload = _run_json(
        env=env,
        args=[
            *base_run_args,
            "--mock",
            "--stage-b",
            "--mock-stage-b-mode",
            "native",
        ],
        cwd=repo_root,
        expected_returncode=0,
    )
    assert native_payload["ok"] is True
    assert native_payload["stages"]["B"]["status"] == "pass"

    compat_payload = _run_json(
        env=env,
        args=[
            *base_run_args,
            "--mock",
            "--stage-b",
            "--mock-stage-b-mode",
            "compat",
        ],
        cwd=repo_root,
        expected_returncode=0,
    )
    assert compat_payload["ok"] is True
    assert compat_payload["stages"]["B"]["status"] == "pass"
