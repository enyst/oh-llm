from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from shutil import which


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _json_line(stdout: str) -> dict:
    text = (stdout or "").strip()
    assert text
    return json.loads(text.splitlines()[-1])


def test_openai_sdk_smoke_script_help() -> None:
    if which("uv") is None:
        return

    proc = subprocess.run(
        ["uv", "run", "python", "scripts/openai_sdk_smoke.py", "--help"],
        cwd=str(_repo_root()),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout


def test_openai_sdk_smoke_script_mock_offline(tmp_path: Path) -> None:
    if which("uv") is None:
        return

    env = dict(os.environ)
    env["HOME"] = str(tmp_path)
    env["OH_LLM_AGENT_SDK_PATH"] = str(tmp_path / "agent-sdk")
    (tmp_path / "agent-sdk").mkdir(parents=True, exist_ok=True)

    runs_dir = tmp_path / "runs"
    proc = subprocess.run(
        [
            "uv",
            "run",
            "python",
            "scripts/openai_sdk_smoke.py",
            "--mock",
            "--stage-b",
            "--runs-dir",
            str(runs_dir),
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
    assert payload["run_dir"]
    assert payload["stages"]["A"]["status"] == "pass"
    assert payload["stages"]["B"]["status"] == "pass"

