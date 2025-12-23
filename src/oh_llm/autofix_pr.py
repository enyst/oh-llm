from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from oh_llm.agent_sdk import AgentSdkError
from oh_llm.redaction import Redactor

_EPHEMERAL_PARTS = {
    ".venv",
    "venv",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".cache",
    "__pycache__",
}


def _is_ephemeral(path: str) -> bool:
    norm = path.replace("\\", "/").lstrip("./")
    if norm.endswith(".pyc"):
        return True
    parts = [p for p in norm.split("/") if p]
    if parts and parts[-1] == ".DS_Store":
        return True
    return any(part in _EPHEMERAL_PARTS for part in parts)


def _run(
    args: list[str],
    *,
    cwd: Path,
    check: bool,
) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    if check and proc.returncode != 0:
        raise AgentSdkError(
            "Command failed: "
            + " ".join(args)
            + "\n"
            + (proc.stdout or "")
            + (proc.stderr or "")
        )
    return proc


def _run_git(
    repo: Path, args: list[str], *, check: bool = True
) -> subprocess.CompletedProcess[str]:
    return _run(["git", "-C", str(repo), *args], cwd=repo, check=check)


def _run_gh(repo: Path, args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return _run(["gh", *args], cwd=repo, check=check)


def current_branch(repo: Path) -> str:
    proc = _run_git(repo, ["rev-parse", "--abbrev-ref", "HEAD"])
    branch = (proc.stdout or "").strip()
    if not branch:
        raise AgentSdkError("Unable to determine current branch in SDK worktree.")
    return branch


@dataclass(frozen=True)
class ChangeSelection:
    paths: tuple[str, ...]
    skipped_ephemeral: tuple[str, ...]

    def as_json(self) -> dict[str, Any]:
        return {
            "paths": list(self.paths),
            "skipped_ephemeral": list(self.skipped_ephemeral),
        }


_STATUS_RENAME = re.compile(r"^..\s+(?P<old>.+?)\s+->\s+(?P<new>.+)$")


def _unquote_porcelain_path(value: str) -> str:
    # Porcelain v1 quotes weird filenames; good enough for our v1 use.
    return value.strip().strip('"')


def _parse_porcelain_line_paths(line: str) -> list[str]:
    if not line:
        return []

    # `XY <path>` (possibly with rename `old -> new`)
    if len(line) < 4:
        return []

    match = _STATUS_RENAME.match(line)
    if match:
        old = _unquote_porcelain_path(match.group("old"))
        new = _unquote_porcelain_path(match.group("new"))
        return [p for p in [old, new] if p]

    path = _unquote_porcelain_path(line[3:])
    return [path] if path else []


def select_paths_to_commit(repo: Path) -> ChangeSelection:
    proc = _run_git(repo, ["status", "--porcelain=v1"])
    raw_lines = [ln.rstrip("\n") for ln in (proc.stdout or "").splitlines()]

    candidates: list[str] = []
    for line in raw_lines:
        candidates.extend(_parse_porcelain_line_paths(line))

    unique = sorted(set(p.lstrip("./") for p in candidates if p))
    paths: list[str] = []
    skipped: list[str] = []
    for path in unique:
        if _is_ephemeral(path):
            skipped.append(path)
        else:
            paths.append(path)

    return ChangeSelection(paths=tuple(paths), skipped_ephemeral=tuple(skipped))

def stage_selection(repo: Path, selection: ChangeSelection) -> None:
    _run_git(repo, ["add", "-A"])
    if selection.skipped_ephemeral:
        # Best-effort: if a path disappears between status and staging, ignore it.
        _run_git(repo, ["reset", "--", *selection.skipped_ephemeral], check=False)


def ensure_commit(
    *,
    repo: Path,
    message: str,
    selection: ChangeSelection,
) -> str:
    stage_selection(repo, selection)

    extras: list[str] = []
    name = _run_git(repo, ["config", "--get", "user.name"], check=False).stdout.strip()
    email = _run_git(repo, ["config", "--get", "user.email"], check=False).stdout.strip()
    if not name:
        extras += ["-c", "user.name=oh-llm"]
    if not email:
        extras += ["-c", "user.email=oh-llm@example.invalid"]

    proc = _run_git(repo, [*extras, "commit", "-m", message], check=False)
    if proc.returncode != 0:
        raise AgentSdkError(
            "Unable to create commit in SDK worktree.\n"
            "Make sure there are staged changes and git user.name/user.email are set.\n"
            + (proc.stdout or "")
            + (proc.stderr or "")
        )

    sha = _run_git(repo, ["rev-parse", "HEAD"]).stdout.strip()
    if not sha:
        raise AgentSdkError("Unable to determine commit SHA after commit.")
    return sha


def ensure_remote(repo: Path, *, remote: str, url: str) -> None:
    if not remote:
        raise AgentSdkError("Missing remote name.")
    if not url:
        raise AgentSdkError("Missing remote URL.")

    proc = _run_git(repo, ["remote", "get-url", remote], check=False)
    if proc.returncode == 0:
        current = (proc.stdout or "").strip()
        if current != url:
            _run_git(repo, ["remote", "set-url", remote, url])
        return

    _run_git(repo, ["remote", "add", remote, url])


def push_branch(repo: Path, *, remote: str, branch: str) -> None:
    _run_git(repo, ["push", "-u", remote, branch])


def gh_user_login(repo: Path) -> str:
    proc = _run_gh(repo, ["api", "user", "--jq", ".login"])
    login = (proc.stdout or "").strip()
    if not login:
        raise AgentSdkError("Unable to determine GitHub login via `gh`.")
    return login


def gh_pr_create(
    *,
    repo: Path,
    upstream_repo: str,
    base: str,
    head: str,
    title: str,
    body_file: Path,
    draft: bool,
) -> str:
    args = [
        "pr",
        "create",
        "--repo",
        upstream_repo,
        "--base",
        base,
        "--head",
        head,
        "--title",
        title,
        "--body-file",
        str(body_file),
    ]
    if draft:
        args.append("--draft")

    proc = _run_gh(repo, args, check=False)
    if proc.returncode != 0:
        raise AgentSdkError(
            "Failed to create PR via `gh`.\n"
            + (proc.stdout or "")
            + (proc.stderr or "")
        )

    url = (proc.stdout or "").strip()
    if not url:
        raise AgentSdkError("`gh pr create` succeeded but returned no PR URL.")
    return url


def render_pr_body(
    *,
    profile_name: str | None,
    run_id: str | None,
    model: str | None,
    base_url: str | None,
    validation: dict[str, Any],
    diffstat: str,
    redactor: Redactor,
) -> str:
    lines: list[str] = []
    lines.append("Autogenerated by `oh-llm`.\n")
    if profile_name:
        lines.append(f"- profile: `{profile_name}`\n")
    if model:
        lines.append(f"- model: `{model}`\n")
    if base_url:
        lines.append(f"- base_url: `{base_url}`\n")
    if run_id:
        lines.append(f"- run_id: `{run_id}`\n")

    lines.append("\n## Validation\n")
    ok = validation.get("ok")
    stages = validation.get("stages") if isinstance(validation.get("stages"), dict) else {}
    lines.append(f"- ok: `{ok}`\n")
    if stages:
        stage_a = stages.get("a") if isinstance(stages.get("a"), dict) else {}
        stage_b = stages.get("b") if isinstance(stages.get("b"), dict) else {}
        lines.append(f"- stage_a: `{stage_a.get('ok')}`\n")
        lines.append(f"- stage_b: `{stage_b.get('ok')}`\n")

    lines.append("\n## Changes\n")
    lines.append("```text\n")
    lines.append((diffstat or "").rstrip() + "\n")
    lines.append("```\n")

    return redactor.redact_text("".join(lines))


def git_show_stat(repo: Path, *, rev: str = "HEAD") -> str:
    proc = _run_git(repo, ["show", "--stat", "--oneline", "--no-color", rev])
    return (proc.stdout or "").strip()
