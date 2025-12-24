from __future__ import annotations

import json
import tarfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from oh_llm.cli import ExitCode, app

pytestmark = pytest.mark.unit


def _tar_members(path: Path) -> set[str]:
    with tarfile.open(path, "r:gz") as tar:
        return {m.name for m in tar.getmembers()}


def test_runs_export_creates_tarball(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Force a temp runs dir so the test is self-contained.
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    monkeypatch.setenv("OH_LLM_RUNS_DIR", str(runs_dir))

    run_dir = runs_dir / "20250101_000000_demo"
    (run_dir / "logs").mkdir(parents=True)
    (run_dir / "artifacts").mkdir(parents=True)

    (run_dir / "run.json").write_text(json.dumps({"schema_version": 1}) + "\n", encoding="utf-8")
    (run_dir / "logs" / "run.log").write_text("hello\n", encoding="utf-8")
    (run_dir / "artifacts" / "a.txt").write_text("artifact\n", encoding="utf-8")

    output_path = tmp_path / "out.tar.gz"
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "runs",
            "export",
            run_dir.name,
            "--output",
            str(output_path),
            "--json",
        ],
    )
    assert result.exit_code == ExitCode.OK, result.stdout
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert Path(payload["export_path"]) == output_path

    assert output_path.exists()
    members = _tar_members(output_path)
    assert f"{run_dir.name}/run.json" in members
    assert f"{run_dir.name}/logs/run.log" in members
    assert f"{run_dir.name}/artifacts/a.txt" in members

