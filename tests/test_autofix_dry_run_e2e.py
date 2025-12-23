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


def _write_fake_openhands(tmp_path: Path, *, secret_value: str) -> Path:
    path = tmp_path / "fake_openhands.py"
    path.write_text(
        (
            "#!/usr/bin/env python3\n"
            "import sys\n"
            f"print('hello {secret_value}')\n"
            "print('args=' + ' '.join(sys.argv[1:]))\n"
        ),
        encoding="utf-8",
    )
    path.chmod(0o700)
    return path


def _write_repro_script(artifacts_dir: Path, *, secret_env: str) -> Path:
    script_path = artifacts_dir / "autofix_repro.py"
    # Intentionally read secrets from env at runtime (so the file itself never contains them).
    print_line = 'print(json.dumps({"ok": True, "note": f"secret={secret}", "stage": args.stage}))'
    script_path.write_text(
        (
            "#!/usr/bin/env python3\n"
            "from __future__ import annotations\n"
            "\n"
            "import argparse\n"
            "import json\n"
            "import os\n"
            "import sys\n"
            "\n"
            "def main() -> int:\n"
            "    parser = argparse.ArgumentParser()\n"
            "    parser.add_argument('--stage', required=True)\n"
            "    args = parser.parse_args()\n"
            f"    secret = os.environ.get({secret_env!r}, '')\n"
            f"    {print_line}\n"
            "    return 0\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    sys.exit(main())\n"
        ),
        encoding="utf-8",
    )
    script_path.chmod(0o700)
    return script_path


def _assert_no_secret_in_artifacts(artifacts_dir: Path, *, secret_value: str) -> None:
    for path in sorted(artifacts_dir.rglob("*")):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        assert secret_value not in text, f"secret leaked in {path}"


def test_autofix_dry_run_smoke_offline(tmp_path: Path) -> None:
    if which("uv") is None:
        pytest.skip("uv is required for this e2e test")

    repo_root = _repo_root()

    secret_env = "TEST_SECRET_ENV"
    secret_value = "super-secret-value"

    sdk_repo = tmp_path / "agent-sdk"
    sdk_repo.mkdir()
    _git(sdk_repo, "init")
    (sdk_repo / "README.md").write_text("sdk\n", encoding="utf-8")
    _git_commit(sdk_repo, message="init")

    runs_dir = tmp_path / "runs"
    run_dir = runs_dir / "20250102_000000_demo_dryrun"
    artifacts_dir = run_dir / "artifacts"
    logs_dir = run_dir / "logs"
    artifacts_dir.mkdir(parents=True, exist_ok=False)
    logs_dir.mkdir(parents=True, exist_ok=True)

    (logs_dir / "run.log").write_text(f"failed: {secret_value}\n", encoding="utf-8")
    run_record = {
        "schema_version": 1,
        "run_id": "run_dryrun",
        "created_at": "2025-01-02T00:00:00+00:00",
        "profile": {
            "name": "demo",
            "model": "demo-model",
            "base_url": "https://example.invalid/v1",
            "redact_env": [secret_env],
        },
        "stages": {"A": {"status": "fail"}, "B": {"status": "fail"}},
        "failure": {"classification": "sdk_or_provider_bug"},
    }
    (run_dir / "run.json").write_text(json.dumps(run_record) + "\n", encoding="utf-8")

    _write_repro_script(artifacts_dir, secret_env=secret_env)

    # Prepare the SDK worktree with a change so dry-run PR creation has something to commit.
    worktree_path = artifacts_dir / "autofix_sdk_worktree"
    _git(sdk_repo, "worktree", "add", "-b", "oh-llm-e2e", str(worktree_path), "HEAD")
    (worktree_path / "CHANGED.txt").write_text("changed\n", encoding="utf-8")

    fork_repo = tmp_path / "fork.git"
    fork_repo.mkdir()
    _git(fork_repo, "init", "--bare")

    fake_openhands = _write_fake_openhands(tmp_path, secret_value=secret_value)

    env = dict(os.environ)
    env["HOME"] = str(tmp_path)
    env["OH_LLM_AGENT_SDK_PATH"] = str(sdk_repo)
    env[secret_env] = secret_value

    cmd = [
        "uv",
        "run",
        "oh-llm",
        "autofix",
        "start",
        "--run",
        run_dir.name,
        "--runs-dir",
        str(runs_dir),
        "--openhands-bin",
        str(fake_openhands),
        "--fork-url",
        str(fork_repo),
        "--fork-owner",
        "testuser",
        "--dry-run",
        "--json",
    ]
    proc = subprocess.run(cmd, cwd=str(repo_root), env=env, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr or proc.stdout

    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    assert payload["pr"]["dry_run"] is True
    assert payload["pr"]["url"] is None

    # Ensure dry-run did not push anything to the bare fork repo.
    refs = _git(fork_repo, "for-each-ref", "refs/heads").stdout
    assert refs.strip() == ""

    # Ensure the secret value is not present in any generated artifacts.
    _assert_no_secret_in_artifacts(artifacts_dir, secret_value=secret_value)
