from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class RunNotFoundError(ValueError):
    pass


class RunAmbiguousError(ValueError):
    pass


@dataclass(frozen=True)
class RunSummary:
    run_id: str | None
    created_at: str | None
    run_dir: Path
    profile_name: str | None
    stage_statuses: dict[str, str]
    status: str

    def as_json(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "created_at": self.created_at,
            "run_dir": str(self.run_dir),
            "profile_name": self.profile_name,
            "stages": dict(self.stage_statuses),
            "status": self.status,
        }


def list_run_dirs(runs_dir: Path) -> list[Path]:
    if not runs_dir.exists():
        return []
    if not runs_dir.is_dir():
        return []
    run_dirs = [p for p in runs_dir.iterdir() if p.is_dir()]
    return sorted(run_dirs, key=lambda p: p.name, reverse=True)


def read_run_record(run_dir: Path) -> dict[str, Any] | None:
    path = run_dir / "run.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _compute_status(stage_statuses: dict[str, str]) -> str:
    statuses = [v for v in stage_statuses.values() if v]
    if any(v == "fail" for v in statuses):
        return "fail"
    if any(v not in {"pass", "not_run"} for v in statuses):
        return "unknown"
    if any(v == "not_run" for v in statuses):
        return "partial"
    if statuses and all(v == "pass" for v in statuses):
        return "pass"
    return "unknown"


def summarize_run(run_dir: Path) -> RunSummary:
    record = read_run_record(run_dir) or {}
    stages = record.get("stages") if isinstance(record.get("stages"), dict) else {}

    stage_statuses: dict[str, str] = {}
    if isinstance(stages, dict):
        for key, value in stages.items():
            if not isinstance(key, str) or not isinstance(value, dict):
                continue
            status = value.get("status")
            if isinstance(status, str):
                stage_statuses[key] = status

    profile_name: str | None = None
    profile = record.get("profile")
    if isinstance(profile, dict):
        name = profile.get("name")
        if isinstance(name, str):
            profile_name = name

    run_id = record.get("run_id") if isinstance(record.get("run_id"), str) else None
    created_at = (
        record.get("created_at") if isinstance(record.get("created_at"), str) else None
    )
    status = _compute_status(stage_statuses)

    return RunSummary(
        run_id=run_id,
        created_at=created_at,
        run_dir=run_dir,
        profile_name=profile_name,
        stage_statuses=stage_statuses,
        status=status,
    )


def resolve_run_dir(runs_dir: Path, run_ref: str) -> Path:
    """Resolve a run reference (run_id or directory name/prefix) to a unique run dir."""
    run_ref = (run_ref or "").strip()
    if not run_ref:
        raise RunNotFoundError("Missing run reference.")

    candidates: list[Path] = []
    for run_dir in list_run_dirs(runs_dir):
        if run_dir.name == run_ref or run_dir.name.startswith(run_ref):
            candidates.append(run_dir)
            continue

        record = read_run_record(run_dir)
        if record and record.get("run_id") == run_ref:
            candidates.append(run_dir)
            continue

        run_id = record.get("run_id") if record else None
        if isinstance(run_id, str) and run_id.startswith(run_ref):
            candidates.append(run_dir)

    if not candidates:
        raise RunNotFoundError(f"Run not found: {run_ref}")

    # Prefer exact name matches, then exact run_id matches, then newest by dir name.
    exact_name = [c for c in candidates if c.name == run_ref]
    if len(exact_name) == 1:
        return exact_name[0]

    exact_id = []
    for c in candidates:
        rec = read_run_record(c) or {}
        if rec.get("run_id") == run_ref:
            exact_id.append(c)
    if len(exact_id) == 1:
        return exact_id[0]

    candidates = sorted(set(candidates), key=lambda p: p.name, reverse=True)
    if len(candidates) == 1:
        return candidates[0]

    hint = ", ".join([c.name for c in candidates[:5]])
    raise RunAmbiguousError(f"Run reference is ambiguous: {run_ref} (matches: {hint} …)")

