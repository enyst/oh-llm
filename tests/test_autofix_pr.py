from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from oh_llm.cli import ExitCode, app

pytestmark = pytest.mark.unit


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )


def _git_commit(repo: Path, *, message: str) -> None:
    _git(repo, "add", "-A")
    _git(
        repo,
        "-c",
        "user.name=oh-llm",
        "-c",
        "user.email=oh-llm@example.invalid",
        "commit",
        "-m",
        message,
    )


def _setup_sdk_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    sdk_repo = tmp_path / "agent-sdk"
    sdk_repo.mkdir()
    _git(sdk_repo, "init")
    (sdk_repo / "README.md").write_text("sdk\n", encoding="utf-8")
    _git_commit(sdk_repo, message="init")
    monkeypatch.setenv("OH_LLM_AGENT_SDK_PATH", str(sdk_repo))
    return sdk_repo


def _write_run(
    runs_dir: Path,
    *,
    dirname: str,
    run_id: str,
    profile_name: str,
    secret_env: str,
) -> Path:
    run_dir = runs_dir / dirname
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_id": run_id,
                "created_at": "2025-01-02T00:00:00+00:00",
                "profile": {
                    "name": profile_name,
                    "model": "demo-model",
                    "base_url": "https://example.invalid/v1",
                    "redact_env": [secret_env],
                },
                "stages": {"A": {"status": "fail"}, "B": {"status": "fail"}},
                "failure": {"classification": "sdk_or_provider_bug"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return run_dir


def _write_validation_ok(artifacts_dir: Path) -> Path:
    path = artifacts_dir / "autofix_validation.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "created_at": "2025-01-02T00:00:00+00:00",
                "ok": True,
                "stages": {"a": {"ok": True}, "b": {"ok": True}},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _write_fake_gh(tmp_path: Path, *, log_path: Path) -> Path:
    gh_path = tmp_path / "gh"
    gh_path.write_text(
        (
            "#!/usr/bin/env python3\n"
            "from __future__ import annotations\n"
            "import os, sys\n"
            "log=os.environ.get('GH_LOG')\n"
            "if log:\n"
            "  with open(log,'a',encoding='utf-8') as f:\n"
            "    f.write(' '.join(sys.argv[1:])+'\\n')\n"
            "args=sys.argv[1:]\n"
            "if args[:2]==['pr','create']:\n"
            "  print('https://github.com/OpenHands/software-agent-sdk/pull/123')\n"
            "  sys.exit(0)\n"
            "if args[:2]==['api','user'] and '--jq' in args:\n"
            "  print('testuser')\n"
            "  sys.exit(0)\n"
            "sys.stderr.write('unsupported gh invocation: '+ ' '.join(args)+'\\n')\n"
            "sys.exit(2)\n"
        ),
        encoding="utf-8",
    )
    gh_path.chmod(0o700)
    log_path.write_text("", encoding="utf-8")
    return gh_path


def test_autofix_pr_commits_pushes_and_creates_pr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    _setup_sdk_repo(tmp_path, monkeypatch)

    secret_env = "TEST_SECRET_ENV"
    secret_value = "super-secret-value"
    monkeypatch.setenv(secret_env, secret_value)

    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    run_dir = _write_run(
        runs_dir,
        dirname="20250102_000000_demo_pr",
        run_id="run_pr123",
        profile_name="demo",
        secret_env=secret_env,
    )
    _write_validation_ok(run_dir / "artifacts")

    # Create worktree and make a change inside it.
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "autofix",
            "worktree",
            "--run",
            run_dir.name,
            "--runs-dir",
            str(runs_dir),
            "--keep-worktree",
            "--json",
        ],
    )
    assert result.exit_code == ExitCode.OK
    payload = json.loads(result.stdout)
    worktree_path = Path(payload["worktree"]["worktree"]["path"])
    (worktree_path / "README.md").write_text("sdk changed\n", encoding="utf-8")

    # Set up a local bare repo as the "fork" push target.
    fork_repo = tmp_path / "fork.git"
    fork_repo.mkdir()
    _git(fork_repo, "init", "--bare")

    gh_log = tmp_path / "gh.log"
    fake_bin = tmp_path / "fakebin"
    fake_bin.mkdir()
    _write_fake_gh(fake_bin, log_path=gh_log)
    monkeypatch.setenv("GH_LOG", str(gh_log))
    monkeypatch.setenv("PATH", f"{fake_bin}{os.pathsep}{os.environ.get('PATH','')}")

    pr_result = runner.invoke(
        app,
        [
            "autofix",
            "pr",
            "--run",
            run_dir.name,
            "--runs-dir",
            str(runs_dir),
            "--fork-url",
            str(fork_repo),
            "--fork-owner",
            "testuser",
            "--json",
        ],
    )
    assert pr_result.exit_code == ExitCode.OK
    pr_payload = json.loads(pr_result.stdout)
    assert pr_payload["ok"] is True
    assert pr_payload["pr_url"].endswith("/pull/123")

    pr_record = Path(pr_payload["artifacts"]["pr_record_json"]).read_text(encoding="utf-8")
    pr_body = Path(pr_payload["artifacts"]["pr_body_md"]).read_text(encoding="utf-8")
    assert secret_value not in pr_record
    assert secret_value not in pr_body

    # Verify the branch was pushed to the bare fork.
    branch = _git(worktree_path, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    refs = _git(fork_repo, "show-ref", "--heads").stdout
    assert f"refs/heads/{branch}" in refs

    # Verify `gh pr create` was invoked.
    gh_calls = gh_log.read_text(encoding="utf-8")
    assert "pr create" in gh_calls


def test_autofix_pr_handles_renames_in_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    _setup_sdk_repo(tmp_path, monkeypatch)

    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    run_dir = _write_run(
        runs_dir,
        dirname="20250102_000000_demo_rename",
        run_id="run_rename123",
        profile_name="demo",
        secret_env="TEST_SECRET_ENV",
    )
    _write_validation_ok(run_dir / "artifacts")

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "autofix",
            "worktree",
            "--run",
            run_dir.name,
            "--runs-dir",
            str(runs_dir),
            "--keep-worktree",
            "--json",
        ],
    )
    assert result.exit_code == ExitCode.OK
    payload = json.loads(result.stdout)
    worktree_path = Path(payload["worktree"]["worktree"]["path"])

    _git(worktree_path, "mv", "README.md", "README2.md")

    fork_repo = tmp_path / "fork.git"
    fork_repo.mkdir()
    _git(fork_repo, "init", "--bare")

    gh_log = tmp_path / "gh.log"
    fake_bin = tmp_path / "fakebin"
    fake_bin.mkdir()
    _write_fake_gh(fake_bin, log_path=gh_log)
    monkeypatch.setenv("GH_LOG", str(gh_log))
    monkeypatch.setenv("PATH", f"{fake_bin}{os.pathsep}{os.environ.get('PATH','')}")

    pr_result = runner.invoke(
        app,
        [
            "autofix",
            "pr",
            "--run",
            run_dir.name,
            "--runs-dir",
            str(runs_dir),
            "--fork-url",
            str(fork_repo),
            "--fork-owner",
            "testuser",
            "--json",
        ],
    )
    assert pr_result.exit_code == ExitCode.OK


def test_autofix_pr_dry_run_does_not_push_or_create_pr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    _setup_sdk_repo(tmp_path, monkeypatch)

    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    run_dir = _write_run(
        runs_dir,
        dirname="20250102_000000_demo_dryrun",
        run_id="run_dryrun",
        profile_name="demo",
        secret_env="TEST_SECRET_ENV",
    )
    _write_validation_ok(run_dir / "artifacts")

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "autofix",
            "worktree",
            "--run",
            run_dir.name,
            "--runs-dir",
            str(runs_dir),
            "--keep-worktree",
            "--json",
        ],
    )
    assert result.exit_code == ExitCode.OK
    payload = json.loads(result.stdout)
    worktree_path = Path(payload["worktree"]["worktree"]["path"])
    (worktree_path / "README.md").write_text("sdk changed\n", encoding="utf-8")

    fork_repo = tmp_path / "fork.git"
    fork_repo.mkdir()
    _git(fork_repo, "init", "--bare")

    gh_log = tmp_path / "gh.log"
    fake_bin = tmp_path / "fakebin"
    fake_bin.mkdir()
    _write_fake_gh(fake_bin, log_path=gh_log)
    monkeypatch.setenv("GH_LOG", str(gh_log))
    monkeypatch.setenv("PATH", f"{fake_bin}{os.pathsep}{os.environ.get('PATH','')}")

    pr_result = runner.invoke(
        app,
        [
            "autofix",
            "pr",
            "--run",
            run_dir.name,
            "--runs-dir",
            str(runs_dir),
            "--fork-url",
            str(fork_repo),
            "--fork-owner",
            "testuser",
            "--dry-run",
            "--json",
        ],
    )
    assert pr_result.exit_code == ExitCode.OK
    pr_payload = json.loads(pr_result.stdout)
    assert pr_payload["ok"] is True
    assert pr_payload["dry_run"] is True
    assert pr_payload["pr_url"] is None

    pr_record_path = Path(pr_payload["artifacts"]["pr_record_json"])
    assert pr_record_path.name == "autofix_upstream_pr_dry_run.json"

    gh_calls = gh_log.read_text(encoding="utf-8")
    assert "pr create" not in gh_calls

    refs = _git(fork_repo, "for-each-ref", "refs/heads").stdout
    assert refs.strip() == ""


def test_autofix_pr_refuses_when_validation_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    _setup_sdk_repo(tmp_path, monkeypatch)

    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    run_dir = _write_run(
        runs_dir,
        dirname="20250102_000000_demo_no_validation",
        run_id="run_noval",
        profile_name="demo",
        secret_env="TEST_SECRET_ENV",
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["autofix", "pr", "--run", run_dir.name, "--runs-dir", str(runs_dir), "--json"],
    )
    assert result.exit_code == ExitCode.RUN_FAILED
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"] == "missing_validation"
