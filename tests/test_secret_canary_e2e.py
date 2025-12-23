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
    *, env: dict[str, str], args: list[str], cwd: Path
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


def _assert_secret_absent(text: str, *, secret_value: str, context: str) -> None:
    assert secret_value not in (text or ""), f"secret leaked in {context}"


def _assert_no_secret_in_tree(root: Path, *, secret_value: str) -> None:
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        _assert_secret_absent(content, secret_value=secret_value, context=str(path))


def test_secret_canary_never_leaks_in_mock_run(tmp_path: Path) -> None:
    if which("uv") is None:
        pytest.skip("uv is required for this e2e test")

    repo_root = _repo_root()
    runs_dir = tmp_path / "runs"
    sdk_path = tmp_path / "agent-sdk"
    sdk_path.mkdir(parents=True, exist_ok=True)

    secret_env = "TEST_SECRET_CANARY"
    secret_value = "secret-canary-value-123"

    env = dict(os.environ)
    env["HOME"] = str(tmp_path)
    env["OH_LLM_AGENT_SDK_PATH"] = str(sdk_path)
    env[secret_env] = secret_value

    profile_name = "demo"
    add_profile = _run_oh_llm(
        env=env,
        args=[
            "profile",
            "add",
            profile_name,
            "--model",
            "mock-model",
            "--api-key-env",
            secret_env,
            "--json",
        ],
        cwd=repo_root,
    )
    assert add_profile.returncode == 0, add_profile.stderr or add_profile.stdout
    _assert_secret_absent(
        add_profile.stdout, secret_value=secret_value, context="profile add stdout"
    )
    _assert_secret_absent(
        add_profile.stderr, secret_value=secret_value, context="profile add stderr"
    )
    assert _json_line(add_profile)["ok"] is True

    run_proc = _run_oh_llm(
        env=env,
        args=[
            "run",
            "--profile",
            profile_name,
            "--runs-dir",
            str(runs_dir),
            "--stage-b",
            "--mock",
            "--mock-stage-b-mode",
            "compat",
            "--json",
        ],
        cwd=repo_root,
    )
    assert run_proc.returncode == 0, run_proc.stderr or run_proc.stdout
    _assert_secret_absent(run_proc.stdout, secret_value=secret_value, context="run stdout")
    _assert_secret_absent(run_proc.stderr, secret_value=secret_value, context="run stderr")
    payload = _json_line(run_proc)
    assert payload["ok"] is True

    run_dir = Path(payload["run_dir"])
    _assert_no_secret_in_tree(run_dir, secret_value=secret_value)

    show_proc = _run_oh_llm(
        env=env,
        args=["runs", "show", run_dir.name, "--runs-dir", str(runs_dir), "--json"],
        cwd=repo_root,
    )
    assert show_proc.returncode == 0, show_proc.stderr or show_proc.stdout
    _assert_secret_absent(show_proc.stdout, secret_value=secret_value, context="runs show stdout")
    _assert_secret_absent(show_proc.stderr, secret_value=secret_value, context="runs show stderr")
    show_payload = _json_line(show_proc)
    assert show_payload["ok"] is True
    _assert_secret_absent(
        json.dumps(show_payload, sort_keys=True),
        secret_value=secret_value,
        context="runs show json payload",
    )
