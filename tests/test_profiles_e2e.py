from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from shutil import which

import pytest

pytestmark = pytest.mark.e2e


def test_profile_add_via_uv_cli_creates_files(tmp_path: Path) -> None:
    if which("uv") is None:
        pytest.skip("uv not available")

    env = dict(os.environ)
    env["HOME"] = str(tmp_path)

    proc = subprocess.run(
        [
            "uv",
            "run",
            "oh-llm",
            "profile",
            "add",
            "demo",
            "--model",
            "gpt-5-mini",
            "--api-key-env",
            "DEMO_API_KEY",
            "--json",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, (proc.stdout or "") + (proc.stderr or "")

    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    assert payload["ok"] is True

    assert (tmp_path / ".openhands" / "llm-profiles" / "demo.json").exists()
    assert (tmp_path / ".oh-llm" / "profiles" / "demo.json").exists()
