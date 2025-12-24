from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from shutil import which

import pytest

pytestmark = pytest.mark.e2e


@pytest.fixture(autouse=True)
def _require_uv() -> None:
    if which("uv") is None:
        pytest.skip("uv not available")


@pytest.fixture
def e2e_env(tmp_path: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["HOME"] = str(tmp_path)
    return env


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _run_oh_llm(
    *,
    env: dict[str, str],
    args: list[str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["uv", "run", "oh-llm", *args],
        cwd=str(_repo_root()),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _json_line(proc: subprocess.CompletedProcess[str]) -> dict:
    text = (proc.stdout or "").strip()
    assert text, proc.stderr or proc.stdout
    return json.loads(text.splitlines()[-1])


def _write_run(*, run_dir: Path, run_id: str, profile_name: str, stages: dict) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "run_id": run_id,
        "created_at": "2025-12-24T00:00:00Z",
        "profile": {"name": profile_name},
        "stages": stages,
    }
    (run_dir / "run.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def test_runs_list_and_show_json_e2e(tmp_path: Path, e2e_env: dict[str, str]) -> None:
    runs_dir = tmp_path / "runs"

    run1_dir = runs_dir / "20251224_000001_demo_aaaa"
    _write_run(
        run_dir=run1_dir,
        run_id="run-aaaa",
        profile_name="demo",
        stages={"A": {"status": "pass"}, "B": {"status": "not_run"}},
    )

    run2_dir = runs_dir / "20251224_000002_broken_bbbb"
    _write_run(
        run_dir=run2_dir,
        run_id="run-bbbb",
        profile_name="broken",
        stages={"A": {"status": "fail"}},
    )

    list_proc = _run_oh_llm(
        env=e2e_env,
        args=["runs", "list", "--runs-dir", str(runs_dir), "--json"],
    )
    assert list_proc.returncode == 0, list_proc.stderr or list_proc.stdout
    payload = _json_line(list_proc)
    runs = payload["runs"]
    assert len(runs) == 2

    # Listed newest-first by run_dir name (descending).
    assert runs[0]["run_id"] == "run-bbbb"
    assert runs[0]["status"] == "fail"
    assert Path(runs[0]["run_dir"]).name == run2_dir.name
    assert runs[1]["run_id"] == "run-aaaa"
    assert runs[1]["status"] == "pass"
    assert Path(runs[1]["run_dir"]).name == run1_dir.name

    show_proc = _run_oh_llm(
        env=e2e_env,
        args=["runs", "show", "run-aaaa", "--runs-dir", str(runs_dir), "--json"],
    )
    assert show_proc.returncode == 0, show_proc.stderr or show_proc.stdout
    show_payload = _json_line(show_proc)
    assert show_payload["ok"] is True
    assert Path(show_payload["run_dir"]).name == run1_dir.name
    assert show_payload["run"]["run_id"] == "run-aaaa"


def test_runs_show_missing_run_exits_nonzero(tmp_path: Path, e2e_env: dict[str, str]) -> None:
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    proc = _run_oh_llm(
        env=e2e_env,
        args=["runs", "show", "does-not-exist", "--runs-dir", str(runs_dir), "--json"],
    )
    assert proc.returncode != 0
    payload = _json_line(proc)
    assert payload["ok"] is False
