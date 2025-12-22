from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from oh_llm.agent_sdk import AgentSdkError
from oh_llm.redaction import Redactor


class OpenHandsError(RuntimeError):
    pass


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(frozen=True)
class OpenHandsArtifacts:
    context_md: Path
    transcript_log: Path
    diff_patch: Path
    run_record_json: Path


def resolve_openhands_bin(value: str) -> str:
    """Resolve an OpenHands CLI binary name/path to an executable path."""
    value = (value or "").strip()
    if not value:
        raise OpenHandsError("Missing OpenHands binary (expected `openhands`).")

    # If the user passes a path, trust it.
    if os.sep in value or (os.altsep and os.altsep in value):
        return value

    resolved = shutil.which(value)
    if not resolved:
        raise OpenHandsError(
            f"OpenHands CLI not found on PATH: {value}. Install OpenHands or pass --openhands-bin."
        )
    return resolved


def build_openhands_task(*, context_path: Path) -> str:
    # Keep the task short; the agent will read the context file for details.
    return (
        "You are an OpenHands agent running in an agent-sdk git worktree. "
        "Read the local context file and follow its instructions:\n\n"
        f"  {context_path}\n"
    )


def write_openhands_context(
    *,
    run_dir: Path,
    worktree_path: Path,
    capsule_md_path: Path,
    repro_script_path: Path,
    worktree_record: dict[str, Any] | None,
    run_record: dict[str, Any],
    redactor: Redactor,
) -> Path:
    artifacts_dir = run_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    profile = run_record.get("profile") if isinstance(run_record.get("profile"), dict) else {}
    profile_name = profile.get("name")
    model = None
    resolved = profile.get("resolved") if isinstance(profile.get("resolved"), dict) else {}
    if isinstance(resolved, dict):
        model = resolved.get("model")

    body = (
        "# oh-llm auto-fix: OpenHands agent context\n\n"
        "Goal: fix OpenHands **software-agent-sdk** compatibility so this run passes.\n\n"
        "## Safety\n\n"
        "- Do not print or persist secrets. Keys must be read from env at runtime.\n"
        "- Assume logs and artifacts are shared; keep output minimal and redact if unsure.\n\n"
        "## Inputs\n\n"
        f"- run_dir: `{run_dir}`\n"
        f"- profile: `{profile_name}`\n"
        f"- model (if known): `{model}`\n"
        f"- worktree_path (cwd): `{worktree_path}`\n"
        f"- capsule: `{capsule_md_path}`\n"
        f"- repro harness: `{repro_script_path}`\n\n"
        "## Repro\n\n"
        "From the worktree root, use the worktree's uv environment to run the harness:\n\n"
        f"```bash\nuv --directory . run python {repro_script_path} --stage a\n"
        f"uv --directory . run python {repro_script_path} --stage b\n```\n\n"
        "If repro requires config files, they live under the run artifacts directory "
        f"(`{run_dir / 'artifacts'}`).\n\n"
        "## Fix workflow\n\n"
        "1) Reproduce Stage A/B failures.\n"
        "2) Identify whether the failure is SDK code, provider quirks, "
        "or tool-call compatibility.\n"
        "3) Implement a patch in this worktree.\n"
        "4) Re-run the repro harness until it passes.\n"
        "5) Run agent-sdk tests/linters if available (best effort).\n"
        "6) Summarize what changed and why.\n\n"
        "## Worktree metadata (FYI)\n\n"
        f"```json\n{json.dumps(worktree_record or {}, indent=2, ensure_ascii=False)}\n```\n"
    )

    context_path = artifacts_dir / "autofix_openhands_context.md"
    context_path.write_text(redactor.redact_text(body), encoding="utf-8")
    try:
        context_path.chmod(0o600)
    except OSError:
        pass
    return context_path


def _run_git(repo: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise AgentSdkError(
            "Command failed: git -C "
            + str(repo)
            + " "
            + " ".join(args)
            + "\n"
            + (proc.stdout or "")
            + (proc.stderr or "")
        )
    return proc


def _write_text_file(path: Path, *, text: str, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    try:
        path.chmod(mode)
    except OSError:
        pass


def run_openhands_cli(
    *,
    openhands_bin: str,
    task: str,
    worktree_path: Path,
    artifacts_dir: Path,
    redactor: Redactor,
) -> tuple[int, Path]:
    """Run OpenHands CLI and stream a redacted transcript to disk."""
    transcript_path = artifacts_dir / "autofix_openhands_transcript.log"
    transcript_path.parent.mkdir(parents=True, exist_ok=True)

    env = dict(os.environ)
    env.setdefault("NO_COLOR", "1")

    # stdout+stderr combined to keep ordering stable.
    proc = subprocess.Popen(
        [openhands_bin, "--headless", "--always-approve", "-t", task],
        cwd=str(worktree_path),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    with transcript_path.open("w", encoding="utf-8") as handle:
        handle.write(redactor.redact_text(f"[{_utc_now_iso()}] openhands_bin: {openhands_bin}\n"))
        handle.write(redactor.redact_text(f"[{_utc_now_iso()}] cwd: {worktree_path}\n"))
        try:
            if proc.stdout is not None:
                for line in proc.stdout:
                    handle.write(redactor.redact_text(line))
        finally:
            exit_code = proc.wait()
            handle.write(redactor.redact_text(f"\n[{_utc_now_iso()}] exit_code: {exit_code}\n"))

    try:
        transcript_path.chmod(0o600)
    except OSError:
        pass

    return exit_code, transcript_path


def write_worktree_diff(
    *,
    worktree_path: Path,
    output_path: Path,
    redactor: Redactor,
) -> None:
    status = _run_git(worktree_path, ["status", "--porcelain=v1"]).stdout
    diff = _run_git(worktree_path, ["diff", "--patch"]).stdout
    payload = (
        "# git status --porcelain=v1\n"
        + (status or "")
        + "\n# git diff --patch\n"
        + (diff or "")
    )
    _write_text_file(output_path, text=redactor.redact_text(payload), mode=0o600)


def write_openhands_run_record(
    *,
    output_path: Path,
    openhands_bin: str,
    worktree_path: Path,
    context_path: Path,
    transcript_path: Path,
    diff_patch_path: Path,
    exit_code: int,
    started_at: str,
    finished_at: str,
    redactor: Redactor,
) -> None:
    record: dict[str, Any] = {
        "schema_version": 1,
        "started_at": started_at,
        "finished_at": finished_at,
        "openhands": {
            "bin": openhands_bin,
            "args": ["--headless", "--always-approve", "-t", "<task>"],
            "cwd": str(worktree_path),
            "exit_code": exit_code,
        },
        "artifacts": {
            "context_md": str(context_path),
            "transcript_log": str(transcript_path),
            "diff_patch": str(diff_patch_path),
        },
    }
    _write_text_file(
        output_path,
        text=json.dumps(redactor.redact_obj(record), indent=2, ensure_ascii=False) + "\n",
        mode=0o600,
    )


def run_openhands_agent(
    *,
    run_dir: Path,
    worktree_path: Path,
    capsule_md_path: Path,
    repro_script_path: Path,
    worktree_record: dict[str, Any] | None,
    run_record: dict[str, Any],
    openhands_bin: str,
    redactor: Redactor,
) -> OpenHandsArtifacts:
    artifacts_dir = run_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    context_path = write_openhands_context(
        run_dir=run_dir,
        worktree_path=worktree_path,
        capsule_md_path=capsule_md_path,
        repro_script_path=repro_script_path,
        worktree_record=worktree_record,
        run_record=run_record,
        redactor=redactor,
    )

    task = build_openhands_task(context_path=context_path)

    started_at = _utc_now_iso()
    exit_code, transcript_path = run_openhands_cli(
        openhands_bin=openhands_bin,
        task=task,
        worktree_path=worktree_path,
        artifacts_dir=artifacts_dir,
        redactor=redactor,
    )
    finished_at = _utc_now_iso()

    diff_patch_path = artifacts_dir / "autofix_openhands_worktree.patch"
    write_worktree_diff(worktree_path=worktree_path, output_path=diff_patch_path, redactor=redactor)

    run_record_path = artifacts_dir / "autofix_openhands_run.json"
    write_openhands_run_record(
        output_path=run_record_path,
        openhands_bin=openhands_bin,
        worktree_path=worktree_path,
        context_path=context_path,
        transcript_path=transcript_path,
        diff_patch_path=diff_patch_path,
        exit_code=exit_code,
        started_at=started_at,
        finished_at=finished_at,
        redactor=redactor,
    )

    return OpenHandsArtifacts(
        context_md=context_path,
        transcript_log=transcript_path,
        diff_patch=diff_patch_path,
        run_record_json=run_record_path,
    )
