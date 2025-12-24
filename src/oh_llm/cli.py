from __future__ import annotations

import json
import os
import subprocess
import tarfile
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import IntEnum
from gzip import GzipFile
from pathlib import Path
from typing import Any

import typer

from oh_llm import __version__
from oh_llm.agent_sdk import (
    AgentSdkError,
    collect_agent_sdk_info,
    is_git_repo,
    resolve_agent_sdk_path,
    uv_run_python,
)
from oh_llm.autofix_capsule import extract_redact_env, write_capsule_artifacts
from oh_llm.autofix_openhands import OpenHandsError, resolve_openhands_bin, run_openhands_agent
from oh_llm.autofix_pr import (
    current_branch,
    ensure_commit,
    ensure_remote,
    gh_pr_create,
    gh_user_login,
    git_show_stat,
    push_branch,
    render_pr_body,
    select_paths_to_commit,
)
from oh_llm.autofix_validation import (
    parse_json_stdout,
    run_repro_stage,
    write_validation_artifact,
)
from oh_llm.failures import failure_from_stages, update_run_failure
from oh_llm.profiles import get_profile, list_profiles, upsert_profile
from oh_llm.redaction import Redactor, redactor_from_env_vars
from oh_llm.run_store import (
    append_log,
    build_run_record,
    create_run_dir,
    default_stage_template,
    resolve_runs_dir,
    write_run_json,
)
from oh_llm.runs import (
    RunAmbiguousError,
    RunNotFoundError,
    list_run_dirs,
    read_run_record,
    resolve_run_dir,
    summarize_run,
)
from oh_llm.stage_a import StageAOutcome, run_stage_a
from oh_llm.stage_b import StageBOutcome, run_stage_b
from oh_llm.worktrees import (
    cleanup_sdk_worktree,
    create_sdk_worktree,
    mark_worktree_cleaned,
    write_worktree_record,
)


class ExitCode(IntEnum):
    OK = 0
    INTERNAL_ERROR = 1
    RUN_FAILED = 2


@dataclass(frozen=True)
class CliContext:
    json_output: bool
    redactor: Redactor


app = typer.Typer(no_args_is_help=True, add_completion=False)
profile_app = typer.Typer(no_args_is_help=True)
runs_app = typer.Typer(no_args_is_help=True)
autofix_app = typer.Typer(no_args_is_help=True)
sdk_app = typer.Typer(no_args_is_help=True)

_STAGE_B_TERMINAL_TYPES: set[str] = {"subprocess", "tmux"}
_STAGE_B_MAX_ITERATIONS_MAX = 200


def _ctx(ctx: typer.Context) -> CliContext:
    obj = ctx.obj
    if isinstance(obj, CliContext):
        return obj
    return CliContext(json_output=False, redactor=Redactor())


def _emit(ctx: CliContext, *, payload: dict[str, Any], text: str) -> None:
    if ctx.json_output:
        typer.echo(json.dumps(ctx.redactor.redact_obj(payload), sort_keys=True))
        return
    typer.echo(text)


def _ctx_with_json_override(ctx: typer.Context, *, json_output: bool) -> CliContext:
    base = _ctx(ctx)
    if json_output:
        return CliContext(json_output=True, redactor=base.redactor)
    return base


def _normalize_stage_b_terminal_type(value: str | None) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return "subprocess"
    return raw


def _validate_stage_b_options(*, terminal_type: str | None, max_iterations: int) -> tuple[str, int]:
    normalized_terminal_type = _normalize_stage_b_terminal_type(terminal_type)
    if normalized_terminal_type not in _STAGE_B_TERMINAL_TYPES:
        raise ValueError(
            "Invalid value for --stage-b-terminal-type. "
            f"Expected one of: {', '.join(sorted(_STAGE_B_TERMINAL_TYPES))}."
        )

    if max_iterations < 1 or max_iterations > _STAGE_B_MAX_ITERATIONS_MAX:
        raise ValueError(
            "Invalid value for --stage-b-max-iterations. "
            f"Expected an integer between 1 and {_STAGE_B_MAX_ITERATIONS_MAX}."
        )

    return normalized_terminal_type, max_iterations


@app.callback()
def _main(
    ctx: typer.Context,
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable JSON output where supported.",
    ),
    version: bool = typer.Option(
        False,
        "--version",
        help="Show version and exit.",
        is_eager=True,
    ),
) -> None:
    if version:
        typer.echo(__version__)
        raise typer.Exit()

    ctx.obj = CliContext(json_output=json_output, redactor=Redactor())


@app.command()
def run(
    ctx: typer.Context,
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable JSON output for this command.",
    ),
    profile: str | None = typer.Option(
        None,
        "--profile",
        help="Profile name/identifier (for run naming).",
    ),
    runs_dir: str | None = typer.Option(
        None,
        "--runs-dir",
        help="Override runs directory (default: $OH_LLM_RUNS_DIR or ~/.oh-llm/runs).",
    ),
    redact_env: list[str] = typer.Option(
        [],
        "--redact-env",
        help="Environment variable name to redact from logs/artifacts (repeatable).",
    ),
    stage_b: bool = typer.Option(
        False,
        "--stage-b",
        help="Run Stage B end-to-end tool calling test (recommended for full compatibility).",
    ),
    stage_b_max_iterations: int = typer.Option(
        50,
        "--stage-b-max-iterations",
        help="Max agent iterations for Stage B (if enabled).",
    ),
    stage_b_terminal_type: str | None = typer.Option(
        "subprocess",
        "--stage-b-terminal-type",
        help="Terminal tool backend for Stage B (subprocess or tmux).",
    ),
    mock: bool = typer.Option(
        False,
        "--mock",
        help="Run in offline mock mode (no network or API keys required).",
    ),
    mock_stage_b_mode: str = typer.Option(
        "native",
        "--mock-stage-b-mode",
        help="Mock Stage B mode (native or compat).",
    ),
) -> None:
    """Run the compatibility suite for a configured LLM."""
    cli_ctx = _ctx_with_json_override(ctx, json_output=json_output)

    resolved_runs_dir = Path(runs_dir).expanduser() if runs_dir else resolve_runs_dir()
    mock_enabled = bool(mock) or bool(os.environ.get("OH_LLM_MOCK"))

    agent_sdk_path = resolve_agent_sdk_path()
    sdk_info = collect_agent_sdk_info(agent_sdk_path)

    run_paths = create_run_dir(runs_dir=resolved_runs_dir, profile_name=profile)
    stages = default_stage_template()

    profile_record = get_profile(profile) if profile else None
    auto_redact: list[str] = []
    if profile_record and profile_record.api_key_env:
        auto_redact.append(profile_record.api_key_env)
    redactor = redactor_from_env_vars(*redact_env, *auto_redact)
    cli_ctx = CliContext(json_output=cli_ctx.json_output, redactor=redactor)

    record = build_run_record(
        run_id=run_paths.run_id,
        created_at=run_paths.created_at,
        profile={
            "name": profile or "unknown",
            "redact_env": sorted(set([*redact_env, *auto_redact])),
            "resolved": profile_record.as_json() if profile_record else None,
        },
        agent_sdk=sdk_info,
        stages=stages,
    )
    record["requested"] = {
        "stage_b": bool(stage_b),
        "mock": bool(mock_enabled),
        "mock_stage_b_mode": str(mock_stage_b_mode),
        "stage_b_terminal_type": stage_b_terminal_type,
        "stage_b_max_iterations": int(stage_b_max_iterations),
    }
    write_run_json(path=run_paths.run_json, run_record=record, redactor=redactor)
    append_log(
        path=run_paths.log_file,
        message="run initialized",
        redactor=redactor,
    )

    if not profile:
        stages["A"]["status"] = "fail"
        stages["A"]["duration_ms"] = 0
        stages["A"]["error"] = {
            "classification": "credential_or_config",
            "type": "ConfigError",
            "message": "Missing required option: --profile",
            "hint": (
                "Create a profile first via `oh-llm profile add ...` "
                "and re-run with `--profile <id>`."
            ),
        }
        update_run_failure(record)
        write_run_json(path=run_paths.run_json, run_record=record, redactor=redactor)
        append_log(
            path=run_paths.log_file,
            message="Stage A: FAIL (missing --profile)",
            redactor=redactor,
        )
        _emit(
            cli_ctx,
            payload={
                "ok": False,
                "run_dir": str(run_paths.run_dir),
                "stages": stages,
                "failure": record.get("failure"),
            },
            text="Missing --profile (see run.json for details).",
        )
        raise typer.Exit(code=ExitCode.RUN_FAILED)

    if profile_record is None:
        stages["A"]["status"] = "fail"
        stages["A"]["duration_ms"] = 0
        stages["A"]["error"] = {
            "classification": "credential_or_config",
            "type": "ConfigError",
            "message": f"Profile not found: {profile}",
            "hint": "Create it via `oh-llm profile add ...` or check `oh-llm profile list`.",
        }
        update_run_failure(record)
        write_run_json(path=run_paths.run_json, run_record=record, redactor=redactor)
        append_log(
            path=run_paths.log_file,
            message="Stage A: FAIL (profile not found)",
            redactor=redactor,
        )
        _emit(
            cli_ctx,
            payload={
                "ok": False,
                "run_dir": str(run_paths.run_dir),
                "stages": stages,
                "failure": record.get("failure"),
            },
            text=f"Profile not found: {profile}",
        )
        raise typer.Exit(code=ExitCode.RUN_FAILED)

    if not profile_record.model or not profile_record.api_key_env:
        stages["A"]["status"] = "fail"
        stages["A"]["duration_ms"] = 0
        stages["A"]["error"] = {
            "classification": "credential_or_config",
            "type": "ConfigError",
            "message": "Profile is missing required fields (model and/or api_key_env).",
            "hint": "Recreate the profile via `oh-llm profile add ... --overwrite`.",
        }
        update_run_failure(record)
        write_run_json(path=run_paths.run_json, run_record=record, redactor=redactor)
        append_log(
            path=run_paths.log_file,
            message="Stage A: FAIL (profile incomplete)",
            redactor=redactor,
        )
        _emit(
            cli_ctx,
            payload={
                "ok": False,
                "run_dir": str(run_paths.run_dir),
                "stages": stages,
                "failure": record.get("failure"),
            },
            text="Profile is incomplete (missing model/api_key_env).",
        )
        raise typer.Exit(code=ExitCode.RUN_FAILED)

    if not mock_enabled and not os.environ.get(profile_record.api_key_env):
        stages["A"]["status"] = "fail"
        stages["A"]["duration_ms"] = 0
        stages["A"]["error"] = {
            "classification": "credential_or_config",
            "type": "ConfigError",
            "message": f"API key env var not set: {profile_record.api_key_env}",
            "hint": f"Export `{profile_record.api_key_env}` and re-run.",
        }
        update_run_failure(record)
        write_run_json(path=run_paths.run_json, run_record=record, redactor=redactor)
        append_log(
            path=run_paths.log_file,
            message="Stage A: FAIL (missing api key env)",
            redactor=redactor,
        )
        _emit(
            cli_ctx,
            payload={
                "ok": False,
                "run_dir": str(run_paths.run_dir),
                "stages": stages,
                "failure": record.get("failure"),
            },
            text="API key env var not set (see run.json for details).",
        )
        raise typer.Exit(code=ExitCode.RUN_FAILED)

    if stage_b:
        try:
            stage_b_terminal_type, stage_b_max_iterations = _validate_stage_b_options(
                terminal_type=stage_b_terminal_type,
                max_iterations=stage_b_max_iterations,
            )
        except ValueError as exc:
            stages["B"]["status"] = "fail"
            stages["B"]["duration_ms"] = 0
            stages["B"]["error"] = {
                "classification": "credential_or_config",
                "type": "ConfigError",
                "message": str(exc),
                "hint": (
                    "Use `--stage-b-terminal-type subprocess` or `--stage-b-terminal-type tmux`, "
                    "and set `--stage-b-max-iterations` to a small positive integer."
                ),
            }
            update_run_failure(record)
            write_run_json(path=run_paths.run_json, run_record=record, redactor=redactor)
            append_log(
                path=run_paths.log_file,
                message="Stage B: FAIL (invalid options)",
                redactor=redactor,
            )
            _emit(
                cli_ctx,
                payload={
                    "ok": False,
                    "run_dir": str(run_paths.run_dir),
                    "stages": stages,
                    "failure": record.get("failure"),
                },
                text=str(exc),
            )
            raise typer.Exit(code=ExitCode.RUN_FAILED)

    # Stage A: connectivity + basic completion
    if mock_enabled:
        outcome = StageAOutcome(
            ok=True,
            duration_ms=1,
            response_preview="MOCK_OK",
            error=None,
            raw={"ok": True, "duration_ms": 1, "response_preview": "MOCK_OK", "mock": True},
        )
    else:
        outcome = run_stage_a(
            agent_sdk_path=agent_sdk_path,
            artifacts_dir=run_paths.artifacts_dir,
            model=profile_record.model,
            base_url=profile_record.base_url,
            api_key_env=profile_record.api_key_env,
            timeout_s=30,
            redactor=redactor,
        )
    stages["A"]["duration_ms"] = outcome.duration_ms
    if outcome.ok:
        stages["A"]["status"] = "pass"
        stages["A"]["result"] = {"response_preview": outcome.response_preview}
        append_log(path=run_paths.log_file, message="Stage A: PASS", redactor=redactor)
    else:
        stages["A"]["status"] = "fail"
        stages["A"]["error"] = outcome.error or {
            "classification": "sdk_or_provider_bug",
            "type": "UnknownError",
            "message": "Stage A failed.",
            "hint": "Inspect run artifacts for details.",
        }
        append_log(
            path=run_paths.log_file,
            message=f"Stage A: FAIL ({stages['A']['error'].get('classification','unknown')})",
            redactor=redactor,
        )

    update_run_failure(record)
    write_run_json(path=run_paths.run_json, run_record=record, redactor=redactor)

    if not outcome.ok or not stage_b:
        payload = {
            "ok": outcome.ok,
            "run_dir": str(run_paths.run_dir),
            "stages": stages,
            "failure": record.get("failure"),
        }
        if cli_ctx.json_output:
            _emit(cli_ctx, payload=payload, text="")
        else:
            status = "PASS" if outcome.ok else "FAIL"
            typer.echo(f"Stage A: {status} (artifacts: {run_paths.run_dir})")
            if not outcome.ok:
                failure = record.get("failure")
                if isinstance(failure, dict):
                    typer.echo(f"Failure classification: {failure.get('classification','unknown')}")
        raise typer.Exit(code=ExitCode.OK if outcome.ok else ExitCode.RUN_FAILED)

    # Stage B: end-to-end agent run (tool calling)
    if mock_enabled:
        mode = str(mock_stage_b_mode or "native").strip().lower()
        if mode not in {"native", "compat"}:
            mode = "native"
        raw = {
            "ok": True,
            "duration_ms": 1,
            "tool_invoked": True,
            "tool_observed": True,
            "tool_command_preview": "echo TOOL_OK",
            "tool_output_preview": "TOOL_OK",
            "final_answer_preview": "TOOL_OK",
            "mock": True,
            "mock_mode": mode,
        }
        # Match real Stage B behavior by writing the probe result artifact.
        probe_result_path = run_paths.artifacts_dir / "stage_b_probe_result.json"
        probe_result_path.write_text(redactor.redact_json(raw), encoding="utf-8")
        try:
            probe_result_path.chmod(0o600)
        except OSError:
            pass

        outcome_b = StageBOutcome(
            ok=True,
            duration_ms=1,
            tool_invoked=True,
            tool_observed=True,
            tool_command_preview="echo TOOL_OK",
            tool_output_preview="TOOL_OK",
            final_answer_preview="TOOL_OK",
            error=None,
            raw=raw,
        )
    else:
        outcome_b = run_stage_b(
            agent_sdk_path=agent_sdk_path,
            artifacts_dir=run_paths.artifacts_dir,
            model=profile_record.model,
            base_url=profile_record.base_url,
            api_key_env=profile_record.api_key_env,
            timeout_s=60,
            max_iterations=stage_b_max_iterations,
            terminal_type=stage_b_terminal_type,
            redactor=redactor,
        )
    stages["B"]["duration_ms"] = outcome_b.duration_ms
    if outcome_b.ok:
        stages["B"]["status"] = "pass"
        stages["B"]["result"] = {
            "tool_invoked": outcome_b.tool_invoked,
            "tool_observed": outcome_b.tool_observed,
            "tool_command_preview": outcome_b.tool_command_preview,
            "tool_output_preview": outcome_b.tool_output_preview,
            "final_answer_preview": outcome_b.final_answer_preview,
        }
        append_log(path=run_paths.log_file, message="Stage B: PASS", redactor=redactor)
    else:
        stages["B"]["status"] = "fail"
        stages["B"]["error"] = outcome_b.error or {
            "classification": "sdk_or_provider_bug",
            "type": "UnknownError",
            "message": "Stage B failed.",
            "hint": "Inspect run artifacts for details.",
        }
        append_log(
            path=run_paths.log_file,
            message=f"Stage B: FAIL ({stages['B']['error'].get('classification','unknown')})",
            redactor=redactor,
        )

    update_run_failure(record)
    write_run_json(path=run_paths.run_json, run_record=record, redactor=redactor)

    ok = stages["A"]["status"] == "pass" and stages["B"]["status"] == "pass"
    payload = {
        "ok": ok,
        "run_dir": str(run_paths.run_dir),
        "stages": stages,
        "failure": record.get("failure"),
    }
    if cli_ctx.json_output:
        _emit(cli_ctx, payload=payload, text="")
    else:
        typer.echo(f"Stage A: PASS (artifacts: {run_paths.run_dir})")
        typer.echo(f"Stage B: {'PASS' if ok else 'FAIL'} (artifacts: {run_paths.run_dir})")
        if not ok:
            failure = record.get("failure")
            if isinstance(failure, dict):
                typer.echo(f"Failure classification: {failure.get('classification','unknown')}")

    raise typer.Exit(code=ExitCode.OK if ok else ExitCode.RUN_FAILED)


@profile_app.command("list")
def profile_list(
    ctx: typer.Context,
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable JSON output for this command.",
    ),
) -> None:
    """List known LLM profiles."""
    cli_ctx = _ctx_with_json_override(ctx, json_output=json_output)
    profiles = list_profiles()
    if cli_ctx.json_output:
        _emit(cli_ctx, payload={"profiles": [profile.as_json() for profile in profiles]}, text="")
        return

    if not profiles:
        typer.echo("No profiles found.")
        return

    for profile in profiles:
        model = profile.model or "(unknown)"
        base_url = f" base_url={profile.base_url}" if profile.base_url else ""
        key_env = f" api_key_env={profile.api_key_env}" if profile.api_key_env else ""
        typer.echo(f"{profile.profile_id}: model={model}{base_url}{key_env}")


@profile_app.command("add")
def profile_add(
    ctx: typer.Context,
    profile_id: str = typer.Argument(..., help="Profile ID (filename stem)."),
    model: str = typer.Option(..., "--model", help="Model name (litellm model string)."),
    base_url: str | None = typer.Option(None, "--base-url", help="Optional base URL."),
    api_key_env: str = typer.Option(
        ...,
        "--api-key-env",
        help="Name of environment variable holding the API key (value is never stored).",
    ),
    overwrite: bool = typer.Option(
        False,
        "--overwrite",
        help="Overwrite existing profile + metadata if present.",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable JSON output for this command.",
    ),
) -> None:
    """Create an LLM profile without persisting secrets."""
    cli_ctx = _ctx_with_json_override(ctx, json_output=json_output)
    try:
        record = upsert_profile(
            profile_id=profile_id,
            model=model,
            base_url=base_url,
            api_key_env=api_key_env,
            overwrite=overwrite,
        )
    except (ValueError, FileExistsError) as exc:
        _emit(cli_ctx, payload={"ok": False, "error": str(exc)}, text=str(exc))
        raise typer.Exit(code=ExitCode.RUN_FAILED)

    _emit(
        cli_ctx,
        payload={"ok": True, "profile": record.as_json()},
        text=f"Saved profile {record.profile_id}.",
    )


@profile_app.command("create", hidden=True)
def profile_create_compat(
    ctx: typer.Context,
    profile_id: str = typer.Argument(..., help="Profile ID (filename stem)."),
    model: str = typer.Option(..., "--model", help="Model name (litellm model string)."),
    base_url: str | None = typer.Option(None, "--base-url", help="Optional base URL."),
    api_key_env: str = typer.Option(
        ...,
        "--api-key-env",
        help="Name of environment variable holding the API key (value is never stored).",
    ),
    overwrite: bool = typer.Option(
        False,
        "--overwrite",
        help="Overwrite existing profile + metadata if present.",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable JSON output for this command.",
    ),
) -> None:
    """Alias for `profile add` (kept for early compatibility)."""
    profile_add(
        ctx,
        profile_id=profile_id,
        model=model,
        base_url=base_url,
        api_key_env=api_key_env,
        overwrite=overwrite,
        json_output=json_output,
    )


@profile_app.command("show")
def profile_show(
    ctx: typer.Context,
    profile_id: str = typer.Argument(..., help="Profile ID to show."),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable JSON output for this command.",
    ),
) -> None:
    """Show a single LLM profile."""
    cli_ctx = _ctx_with_json_override(ctx, json_output=json_output)
    try:
        record = get_profile(profile_id)
    except ValueError as exc:
        _emit(cli_ctx, payload={"ok": False, "error": str(exc)}, text=str(exc))
        raise typer.Exit(code=ExitCode.RUN_FAILED)

    if record is None:
        _emit(
            cli_ctx,
            payload={"ok": False, "error": "not_found", "profile_id": profile_id},
            text=f"Profile not found: {profile_id}",
        )
        raise typer.Exit(code=ExitCode.RUN_FAILED)

    _emit(cli_ctx, payload={"ok": True, "profile": record.as_json()}, text=record.profile_id)


@runs_app.command("list")
def runs_list(
    ctx: typer.Context,
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable JSON output for this command.",
    ),
    runs_dir: str | None = typer.Option(
        None,
        "--runs-dir",
        help="Override runs directory (default: $OH_LLM_RUNS_DIR or ~/.oh-llm/runs).",
    ),
    limit: int = typer.Option(
        20,
        "--limit",
        help="Maximum runs to list.",
    ),
) -> None:
    """List previous runs."""
    cli_ctx = _ctx_with_json_override(ctx, json_output=json_output)
    resolved_runs_dir = Path(runs_dir).expanduser() if runs_dir else resolve_runs_dir()
    summaries = [
        summarize_run(run_dir)
        for run_dir in list_run_dirs(resolved_runs_dir)[: max(limit, 0)]
    ]

    if cli_ctx.json_output:
        _emit(cli_ctx, payload={"runs": [s.as_json() for s in summaries]}, text="")
        return

    if not summaries:
        typer.echo("No runs found.")
        return

    for summary in summaries:
        profile = summary.profile_name or "(unknown)"
        created_at = summary.created_at or "(unknown time)"
        run_id = summary.run_id or "(unknown id)"
        typer.echo(
            f"{summary.status}: {run_id}  {created_at}  {profile}  ({summary.run_dir.name})"
        )


@runs_app.command("show")
def runs_show(
    ctx: typer.Context,
    run: str = typer.Argument(..., help="Run id or run directory name/prefix."),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable JSON output for this command.",
    ),
    runs_dir: str | None = typer.Option(
        None,
        "--runs-dir",
        help="Override runs directory (default: $OH_LLM_RUNS_DIR or ~/.oh-llm/runs).",
    ),
) -> None:
    """Show details for one run."""
    cli_ctx = _ctx_with_json_override(ctx, json_output=json_output)
    resolved_runs_dir = Path(runs_dir).expanduser() if runs_dir else resolve_runs_dir()

    try:
        run_dir = resolve_run_dir(resolved_runs_dir, run)
    except (RunNotFoundError, RunAmbiguousError) as exc:
        _emit(cli_ctx, payload={"ok": False, "error": str(exc)}, text=str(exc))
        raise typer.Exit(code=ExitCode.RUN_FAILED)

    record_path = run_dir / "run.json"
    if not record_path.exists():
        _emit(
            cli_ctx,
            payload={"ok": False, "error": "run.json missing", "run_dir": str(run_dir)},
            text=f"run.json missing in: {run_dir}",
        )
        raise typer.Exit(code=ExitCode.RUN_FAILED)

    payload = read_run_record(run_dir)
    if payload is None:
        _emit(
            cli_ctx,
            payload={"ok": False, "error": "run.json corrupt", "run_dir": str(run_dir)},
            text=f"run.json corrupt in: {run_dir}",
        )
        raise typer.Exit(code=ExitCode.RUN_FAILED)
    if cli_ctx.json_output:
        _emit(cli_ctx, payload={"ok": True, "run_dir": str(run_dir), "run": payload}, text="")
        return

    summary = summarize_run(run_dir)
    typer.echo(f"run_dir: {run_dir}")
    typer.echo(f"run_id: {summary.run_id or '(unknown)'}")
    typer.echo(f"created_at: {summary.created_at or '(unknown)'}")
    typer.echo(f"profile: {summary.profile_name or '(unknown)'}")
    for key in sorted(summary.stage_statuses.keys()):
        typer.echo(f"stage {key}: {summary.stage_statuses[key]}")


def _export_run_dir_tar_gz(*, run_dir: Path, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as raw:
        with GzipFile(fileobj=raw, mode="wb", mtime=0) as gz:
            with tarfile.open(fileobj=gz, mode="w") as tar:
                tar.add(run_dir, arcname=run_dir.name)
    try:
        output_path.chmod(0o600)
    except OSError:
        pass


@runs_app.command("export")
def runs_export(
    ctx: typer.Context,
    run: str = typer.Argument(..., help="Run id or run directory name/prefix to export."),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable JSON output for this command.",
    ),
    runs_dir: str | None = typer.Option(
        None,
        "--runs-dir",
        help="Override runs directory (default: $OH_LLM_RUNS_DIR or ~/.oh-llm/runs).",
    ),
    output: str | None = typer.Option(
        None,
        "--output",
        help="Output archive path (default: <runs_dir>/<run_dir.name>.tar.gz).",
    ),
) -> None:
    """Export a run directory to a tar.gz archive for sharing."""
    cli_ctx = _ctx_with_json_override(ctx, json_output=json_output)
    resolved_runs_dir = Path(runs_dir).expanduser() if runs_dir else resolve_runs_dir()

    try:
        run_dir = resolve_run_dir(resolved_runs_dir, run)
    except (RunNotFoundError, RunAmbiguousError) as exc:
        _emit(cli_ctx, payload={"ok": False, "error": str(exc)}, text=str(exc))
        raise typer.Exit(code=ExitCode.RUN_FAILED)

    if not (run_dir / "run.json").exists():
        _emit(
            cli_ctx,
            payload={"ok": False, "error": "run.json missing", "run_dir": str(run_dir)},
            text=f"run.json missing in: {run_dir}",
        )
        raise typer.Exit(code=ExitCode.RUN_FAILED)

    output_path = (
        Path(output).expanduser() if output else (run_dir.parent / f"{run_dir.name}.tar.gz")
    )
    try:
        _export_run_dir_tar_gz(run_dir=run_dir, output_path=output_path)
    except (OSError, tarfile.TarError) as exc:
        _emit(
            cli_ctx,
            payload={
                "ok": False,
                "error": str(exc),
                "run_dir": str(run_dir),
                "export_path": str(output_path),
            },
            text=str(exc),
        )
        raise typer.Exit(code=ExitCode.RUN_FAILED)

    _emit(
        cli_ctx,
        payload={"ok": True, "run_dir": str(run_dir), "export_path": str(output_path)},
        text=str(output_path),
    )


def _autofix_profile_name_for_branch(*, record: dict[str, Any]) -> str:
    profile = record.get("profile") if isinstance(record.get("profile"), dict) else {}
    resolved = profile.get("resolved") if isinstance(profile.get("resolved"), dict) else {}
    return (
        str(profile.get("name") or "").strip()
        or str(profile.get("model") or "").strip()
        or str(resolved.get("model") or "").strip()
        or "llm"
    )


def _autofix_failure(record: dict[str, Any]) -> dict[str, Any]:
    failure = record.get("failure")
    if isinstance(failure, dict):
        return failure
    stages = record.get("stages") if isinstance(record.get("stages"), dict) else {}
    inferred = failure_from_stages(stages)
    return inferred if isinstance(inferred, dict) else {}


def _autofix_should_refuse(*, classification: str, force: bool) -> bool:
    return classification == "credential_or_config" and not force


def _autofix_load_worktree_record(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


class AutofixWorktreeMissingError(Exception):
    def __init__(self, worktree_path: Path) -> None:
        super().__init__(f"Worktree missing: {worktree_path}")
        self.worktree_path = worktree_path


@dataclass(frozen=True)
class AutofixWorktree:
    worktree_path: Path
    worktree_record_path: Path
    worktree_record: dict[str, Any] | None


def _autofix_ensure_sdk_worktree(
    *,
    artifacts_dir: Path,
    record: dict[str, Any],
    resolved_sdk_path: Path,
    allow_dirty_sdk: bool,
) -> AutofixWorktree:
    worktree_path = artifacts_dir / "autofix_sdk_worktree"
    worktree_record_path = artifacts_dir / "autofix_worktree.json"
    worktree_record = _autofix_load_worktree_record(worktree_record_path)

    if not worktree_path.exists():
        run_id = str(record.get("run_id") or artifacts_dir.parent.name).strip()
        created = create_sdk_worktree(
            agent_sdk_path=resolved_sdk_path,
            worktree_path=worktree_path,
            profile_name=_autofix_profile_name_for_branch(record=record),
            run_id=run_id,
            allow_dirty=allow_dirty_sdk,
            keep_worktree=True,
        )
        write_worktree_record(worktree_record_path, record=created)
        worktree_record = created.as_json()

    if not worktree_path.exists():
        raise AutofixWorktreeMissingError(worktree_path)

    return AutofixWorktree(
        worktree_path=worktree_path,
        worktree_record_path=worktree_record_path,
        worktree_record=worktree_record,
    )


def _autofix_pipeline(
    *,
    cli_ctx: CliContext,
    run_dir: Path,
    record: dict[str, Any],
    agent_sdk_path: str | None,
    allow_dirty_sdk: bool,
    force: bool,
    openhands_bin: str,
    redact_env: list[str],
    upstream_repo: str,
    base: str,
    fork_owner: str | None,
    fork_url: str | None,
    push_remote: str,
    title: str | None,
    draft: bool,
    dry_run: bool,
) -> None:
    failure = _autofix_failure(record)
    classification_value = failure.get("classification")
    classification = classification_value if isinstance(classification_value, str) else "unknown"

    if _autofix_should_refuse(classification=classification, force=force):
        _emit(
            cli_ctx,
            payload={
                "ok": False,
                "error": "refused",
                "reason": "credential_or_config",
                "run_dir": str(run_dir),
                "failure": failure,
            },
            text=(
                "Refusing to auto-fix a credential/config failure by default. "
                "Fix credentials/config and re-run, or pass --force."
            ),
        )
        raise typer.Exit(code=ExitCode.RUN_FAILED)

    redaction_names = sorted(set([*extract_redact_env(record), *redact_env]))
    redactor = redactor_from_env_vars(*redaction_names)

    try:
        resolved_openhands = resolve_openhands_bin(openhands_bin)
    except OpenHandsError as exc:
        _emit(
            cli_ctx,
            payload={"ok": False, "error": str(exc), "run_dir": str(run_dir)},
            text=str(exc),
        )
        raise typer.Exit(code=ExitCode.RUN_FAILED)

    resolved_sdk_path = resolve_agent_sdk_path(Path(agent_sdk_path) if agent_sdk_path else None)
    artifacts_dir = run_dir / "artifacts"
    try:
        ensured = _autofix_ensure_sdk_worktree(
            artifacts_dir=artifacts_dir,
            record=record,
            resolved_sdk_path=resolved_sdk_path,
            allow_dirty_sdk=allow_dirty_sdk,
        )
    except AgentSdkError as exc:
        _emit(
            cli_ctx,
            payload={"ok": False, "error": str(exc), "run_dir": str(run_dir)},
            text=str(exc),
        )
        raise typer.Exit(code=ExitCode.RUN_FAILED)
    except AutofixWorktreeMissingError as exc:
        _emit(
            cli_ctx,
            payload={
                "ok": False,
                "error": "worktree_missing",
                "worktree_path": str(exc.worktree_path),
            },
            text=str(exc),
        )
        raise typer.Exit(code=ExitCode.RUN_FAILED)

    worktree_path = ensured.worktree_path
    worktree_record = ensured.worktree_record

    capsule_artifacts = write_capsule_artifacts(
        run_dir=run_dir,
        run_record=record,
        redactor=redactor,
    )

    try:
        openhands_artifacts = run_openhands_agent(
            run_dir=run_dir,
            worktree_path=worktree_path,
            capsule_md_path=capsule_artifacts.capsule_md,
            repro_script_path=capsule_artifacts.repro_script,
            worktree_record=worktree_record,
            run_record=record,
            openhands_bin=resolved_openhands,
            redactor=redactor,
        )
    except (OpenHandsError, AgentSdkError, OSError, subprocess.SubprocessError) as exc:
        _emit(
            cli_ctx,
            payload={"ok": False, "error": str(exc), "run_dir": str(run_dir)},
            text=str(exc),
        )
        raise typer.Exit(code=ExitCode.RUN_FAILED)

    validation_payload = _autofix_validate_impl(
        run_dir=run_dir,
        record=record,
        redactor=redactor,
        resolved_sdk_path=resolved_sdk_path,
        allow_dirty_sdk=allow_dirty_sdk,
    )
    if validation_payload["ok"] is not True:
        _emit(
            cli_ctx,
            payload={
                "ok": False,
                "error": "validation_failed",
                "run_dir": str(run_dir),
                "worktree_path": str(worktree_path),
                "validation": validation_payload,
                "artifacts": {
                    "capsule_json": str(capsule_artifacts.capsule_json),
                    "capsule_md": str(capsule_artifacts.capsule_md),
                    "repro_script": str(capsule_artifacts.repro_script),
                    "openhands_context_md": str(openhands_artifacts.context_md),
                    "openhands_transcript_log": str(openhands_artifacts.transcript_log),
                    "openhands_diff_patch": str(openhands_artifacts.diff_patch),
                    "openhands_run_record_json": str(openhands_artifacts.run_record_json),
                },
            },
            text="Validation did not pass; refusing to open an upstream PR.",
        )
        raise typer.Exit(code=ExitCode.RUN_FAILED)

    pr_payload = _autofix_pr_impl(
        cli_ctx=cli_ctx,
        run_dir=run_dir,
        record=record,
        redactor=redactor,
        resolved_sdk_path=resolved_sdk_path,
        allow_dirty_sdk=allow_dirty_sdk,
        upstream_repo=upstream_repo,
        base=base,
        fork_owner=fork_owner,
        fork_url=fork_url,
        push_remote=push_remote,
        title=title,
        draft=draft,
        dry_run=dry_run,
    )

    _emit(
        cli_ctx,
        payload={
            "ok": True,
            "run_dir": str(run_dir),
            "worktree_path": str(worktree_path),
            "pr": pr_payload,
            "artifacts": {
                "capsule_json": str(capsule_artifacts.capsule_json),
                "capsule_md": str(capsule_artifacts.capsule_md),
                "repro_script": str(capsule_artifacts.repro_script),
                "openhands_context_md": str(openhands_artifacts.context_md),
                "openhands_transcript_log": str(openhands_artifacts.transcript_log),
                "openhands_diff_patch": str(openhands_artifacts.diff_patch),
                "openhands_run_record_json": str(openhands_artifacts.run_record_json),
                "validation_json": str(artifacts_dir / "autofix_validation.json"),
                "validation_md": str(artifacts_dir / "autofix_validation.md"),
            },
        },
        text=(
            f"Created upstream PR: {pr_payload.get('url')}"
            if not dry_run
            else "Dry-run: prepared upstream PR artifacts (no push, no PR created)."
        ),
    )
    raise typer.Exit(code=ExitCode.OK)


@autofix_app.callback(invoke_without_command=True)
def autofix(
    ctx: typer.Context,
    run: str | None = typer.Option(
        None,
        "--run",
        help="Run id or run directory name/prefix to auto-fix.",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable JSON output for this command.",
    ),
    runs_dir: str | None = typer.Option(
        None,
        "--runs-dir",
        help="Override runs directory (default: $OH_LLM_RUNS_DIR or ~/.oh-llm/runs).",
    ),
    agent_sdk_path: str | None = typer.Option(
        None,
        "--agent-sdk-path",
        help="Path to agent-sdk checkout (default: $OH_LLM_AGENT_SDK_PATH or ~/repos/agent-sdk).",
    ),
    allow_dirty_sdk: bool = typer.Option(
        False,
        "--allow-dirty-sdk",
        help="Allow creating a worktree from a dirty agent-sdk checkout (unsafe).",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Override safety gating for credential/config failures.",
    ),
    openhands_bin: str = typer.Option(
        "openhands",
        "--openhands-bin",
        help="OpenHands CLI executable (default: openhands on PATH).",
    ),
    upstream_repo: str = typer.Option(
        "OpenHands/software-agent-sdk",
        "--upstream-repo",
        help="Upstream repo to open the PR against (owner/name).",
    ),
    base: str = typer.Option(
        "main",
        "--base",
        help="Base branch in the upstream repo.",
    ),
    fork_owner: str | None = typer.Option(
        None,
        "--fork-owner",
        help="Fork owner for the PR head (default: `gh api user --jq .login`).",
    ),
    fork_url: str | None = typer.Option(
        None,
        "--fork-url",
        help=(
            "Fork remote URL to push to (default: "
            "https://github.com/<fork-owner>/software-agent-sdk.git)."
        ),
    ),
    push_remote: str = typer.Option(
        "fork",
        "--push-remote",
        help="Git remote name to push the worktree branch to (default: fork).",
    ),
    title: str | None = typer.Option(
        None,
        "--title",
        help="Override PR title.",
    ),
    draft: bool = typer.Option(
        False,
        "--draft",
        help="Create PR as a draft.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Do everything except push branches or open PRs.",
    ),
    redact_env: list[str] = typer.Option(
        [],
        "--redact-env",
        help="Environment variable name to redact from transcript/diff/PR artifacts (repeatable).",
    ),
) -> None:
    if ctx.invoked_subcommand is not None:
        return

    cli_ctx = _ctx_with_json_override(ctx, json_output=json_output)
    if not run:
        typer.echo(ctx.get_help())
        raise typer.Exit(code=ExitCode.RUN_FAILED)

    resolved_runs_dir = Path(runs_dir).expanduser() if runs_dir else resolve_runs_dir()
    try:
        run_dir = resolve_run_dir(resolved_runs_dir, run)
    except (RunNotFoundError, RunAmbiguousError) as exc:
        _emit(cli_ctx, payload={"ok": False, "error": str(exc)}, text=str(exc))
        raise typer.Exit(code=ExitCode.RUN_FAILED)

    record = read_run_record(run_dir)
    if record is None:
        _emit(
            cli_ctx,
            payload={"ok": False, "error": "run.json missing or corrupt", "run_dir": str(run_dir)},
            text=f"run.json missing or corrupt in: {run_dir}",
        )
        raise typer.Exit(code=ExitCode.RUN_FAILED)

    _autofix_pipeline(
        cli_ctx=cli_ctx,
        run_dir=run_dir,
        record=record,
        agent_sdk_path=agent_sdk_path,
        allow_dirty_sdk=allow_dirty_sdk,
        force=force,
        openhands_bin=openhands_bin,
        redact_env=redact_env,
        upstream_repo=upstream_repo,
        base=base,
        fork_owner=fork_owner,
        fork_url=fork_url,
        push_remote=push_remote,
        title=title,
        draft=draft,
        dry_run=dry_run,
    )


@autofix_app.command("start")
def autofix_start(
    ctx: typer.Context,
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable JSON output for this command.",
    ),
    run: str | None = typer.Option(
        None,
        "--run",
        help="Run id or run directory name/prefix to auto-fix.",
    ),
    runs_dir: str | None = typer.Option(
        None,
        "--runs-dir",
        help="Override runs directory (default: $OH_LLM_RUNS_DIR or ~/.oh-llm/runs).",
    ),
    agent_sdk_path: str | None = typer.Option(
        None,
        "--agent-sdk-path",
        help="Path to agent-sdk checkout (default: $OH_LLM_AGENT_SDK_PATH or ~/repos/agent-sdk).",
    ),
    allow_dirty_sdk: bool = typer.Option(
        False,
        "--allow-dirty-sdk",
        help="Allow creating a worktree from a dirty agent-sdk checkout (unsafe).",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Override safety gating for credential/config failures.",
    ),
    openhands_bin: str = typer.Option(
        "openhands",
        "--openhands-bin",
        help="OpenHands CLI executable (default: openhands on PATH).",
    ),
    upstream_repo: str = typer.Option(
        "OpenHands/software-agent-sdk",
        "--upstream-repo",
        help="Upstream repo to open the PR against (owner/name).",
    ),
    base: str = typer.Option(
        "main",
        "--base",
        help="Base branch in the upstream repo.",
    ),
    fork_owner: str | None = typer.Option(
        None,
        "--fork-owner",
        help="Fork owner for the PR head (default: `gh api user --jq .login`).",
    ),
    fork_url: str | None = typer.Option(
        None,
        "--fork-url",
        help=(
            "Fork remote URL to push to (default: "
            "https://github.com/<fork-owner>/software-agent-sdk.git)."
        ),
    ),
    push_remote: str = typer.Option(
        "fork",
        "--push-remote",
        help="Git remote name to push the worktree branch to (default: fork).",
    ),
    title: str | None = typer.Option(
        None,
        "--title",
        help="Override PR title.",
    ),
    draft: bool = typer.Option(
        False,
        "--draft",
        help="Create PR as a draft.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Do everything except push branches or open PRs.",
    ),
    redact_env: list[str] = typer.Option(
        [],
        "--redact-env",
        help="Environment variable name to redact from transcript/diff/PR artifacts (repeatable).",
    ),
) -> None:
    """Start an auto-fix run (alias for `oh-llm autofix <run>`)."""
    cli_ctx = _ctx_with_json_override(ctx, json_output=json_output)

    if not run:
        typer.echo(ctx.get_help())
        raise typer.Exit(code=ExitCode.RUN_FAILED)

    resolved_runs_dir = Path(runs_dir).expanduser() if runs_dir else resolve_runs_dir()
    try:
        run_dir = resolve_run_dir(resolved_runs_dir, run)
    except (RunNotFoundError, RunAmbiguousError) as exc:
        _emit(cli_ctx, payload={"ok": False, "error": str(exc)}, text=str(exc))
        raise typer.Exit(code=ExitCode.RUN_FAILED)

    record = read_run_record(run_dir)
    if record is None:
        _emit(
            cli_ctx,
            payload={"ok": False, "error": "run.json missing or corrupt", "run_dir": str(run_dir)},
            text=f"run.json missing or corrupt in: {run_dir}",
        )
        raise typer.Exit(code=ExitCode.RUN_FAILED)

    _autofix_pipeline(
        cli_ctx=cli_ctx,
        run_dir=run_dir,
        record=record,
        agent_sdk_path=agent_sdk_path,
        allow_dirty_sdk=allow_dirty_sdk,
        force=force,
        openhands_bin=openhands_bin,
        redact_env=redact_env,
        upstream_repo=upstream_repo,
        base=base,
        fork_owner=fork_owner,
        fork_url=fork_url,
        push_remote=push_remote,
        title=title,
        draft=draft,
        dry_run=dry_run,
    )


@autofix_app.command("worktree")
def autofix_worktree(
    ctx: typer.Context,
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable JSON output for this command.",
    ),
    run: str = typer.Option(
        ...,
        "--run",
        help="Run id or run directory name/prefix to prepare a worktree for.",
    ),
    runs_dir: str | None = typer.Option(
        None,
        "--runs-dir",
        help="Override runs directory (default: $OH_LLM_RUNS_DIR or ~/.oh-llm/runs).",
    ),
    keep_worktree: bool = typer.Option(
        False,
        "--keep-worktree",
        help="Keep the created worktree on disk for debugging (default: clean up).",
    ),
    allow_dirty_sdk: bool = typer.Option(
        False,
        "--allow-dirty-sdk",
        help="Allow creating a worktree from a dirty agent-sdk checkout (unsafe).",
    ),
    agent_sdk_path: str | None = typer.Option(
        None,
        "--agent-sdk-path",
        help="Path to agent-sdk checkout (default: $OH_LLM_AGENT_SDK_PATH or ~/repos/agent-sdk).",
    ),
) -> None:
    """Create an agent-sdk git worktree for an auto-fix run."""
    cli_ctx = _ctx_with_json_override(ctx, json_output=json_output)
    resolved_runs_dir = Path(runs_dir).expanduser() if runs_dir else resolve_runs_dir()

    try:
        run_dir = resolve_run_dir(resolved_runs_dir, run)
    except (RunNotFoundError, RunAmbiguousError) as exc:
        _emit(cli_ctx, payload={"ok": False, "error": str(exc)}, text=str(exc))
        raise typer.Exit(code=ExitCode.RUN_FAILED)

    record = read_run_record(run_dir)
    if record is None:
        _emit(
            cli_ctx,
            payload={"ok": False, "error": "run.json missing or corrupt", "run_dir": str(run_dir)},
            text=f"run.json missing or corrupt in: {run_dir}",
        )
        raise typer.Exit(code=ExitCode.RUN_FAILED)

    run_id = str(record.get("run_id") or run_dir.name).strip()
    profile_obj = record.get("profile") if isinstance(record.get("profile"), dict) else {}
    profile_name = str(profile_obj.get("name") or "unknown").strip()

    resolved_sdk_path = resolve_agent_sdk_path(Path(agent_sdk_path) if agent_sdk_path else None)
    worktree_path = run_dir / "artifacts" / "autofix_sdk_worktree"
    worktree_record_path = run_dir / "artifacts" / "autofix_worktree.json"

    created_record = None
    try:
        created_record = create_sdk_worktree(
            agent_sdk_path=resolved_sdk_path,
            worktree_path=worktree_path,
            profile_name=profile_name,
            run_id=run_id,
            allow_dirty=allow_dirty_sdk,
            keep_worktree=keep_worktree,
        )

        final_record = created_record
        if not keep_worktree:
            cleanup_sdk_worktree(
                agent_sdk_path=resolved_sdk_path,
                worktree_path=worktree_path,
                branch=created_record.branch,
            )
            final_record = mark_worktree_cleaned(created_record)

        write_worktree_record(worktree_record_path, record=final_record)

        _emit(
            cli_ctx,
            payload={
                "ok": True,
                "run_dir": str(run_dir),
                "worktree": final_record.as_json(),
            },
            text=(
                f"Prepared agent-sdk worktree: {final_record.worktree_path} "
                f"(branch {final_record.branch})"
            ),
        )
        raise typer.Exit(code=ExitCode.OK)
    except (AgentSdkError, ValueError) as exc:
        _emit(
            cli_ctx,
            payload={"ok": False, "error": str(exc), "run_dir": str(run_dir)},
            text=str(exc),
        )
        raise typer.Exit(code=ExitCode.RUN_FAILED)

@autofix_app.command("capsule")
def autofix_capsule(
    ctx: typer.Context,
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable JSON output for this command.",
    ),
    run: str = typer.Option(
        ...,
        "--run",
        help="Run id or run directory name/prefix to generate artifacts for.",
    ),
    runs_dir: str | None = typer.Option(
        None,
        "--runs-dir",
        help="Override runs directory (default: $OH_LLM_RUNS_DIR or ~/.oh-llm/runs).",
    ),
    redact_env: list[str] = typer.Option(
        [],
        "--redact-env",
        help="Environment variable name to redact from capsule artifacts (repeatable).",
    ),
) -> None:
    """Generate a repro harness + error capsule for an existing run."""
    cli_ctx = _ctx_with_json_override(ctx, json_output=json_output)
    resolved_runs_dir = Path(runs_dir).expanduser() if runs_dir else resolve_runs_dir()

    try:
        run_dir = resolve_run_dir(resolved_runs_dir, run)
    except (RunNotFoundError, RunAmbiguousError) as exc:
        _emit(cli_ctx, payload={"ok": False, "error": str(exc)}, text=str(exc))
        raise typer.Exit(code=ExitCode.RUN_FAILED)

    record = read_run_record(run_dir)
    if record is None:
        _emit(
            cli_ctx,
            payload={"ok": False, "error": "run.json missing or corrupt", "run_dir": str(run_dir)},
            text=f"run.json missing or corrupt in: {run_dir}",
        )
        raise typer.Exit(code=ExitCode.RUN_FAILED)

    redaction_names = sorted(set([*extract_redact_env(record), *redact_env]))
    redactor = redactor_from_env_vars(*redaction_names)
    artifacts = write_capsule_artifacts(run_dir=run_dir, run_record=record, redactor=redactor)

    _emit(
        cli_ctx,
        payload={
            "ok": True,
            "run_dir": str(run_dir),
            "artifacts": {
                "capsule_json": str(artifacts.capsule_json),
                "capsule_md": str(artifacts.capsule_md),
                "repro_script": str(artifacts.repro_script),
            },
        },
        text=f"Wrote capsule artifacts under: {run_dir / 'artifacts'}",
    )
    raise typer.Exit(code=ExitCode.OK)

@autofix_app.command("agent")
def autofix_agent(
    ctx: typer.Context,
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable JSON output for this command.",
    ),
    run: str = typer.Option(
        ...,
        "--run",
        help="Run id or run directory name/prefix to auto-fix.",
    ),
    runs_dir: str | None = typer.Option(
        None,
        "--runs-dir",
        help="Override runs directory (default: $OH_LLM_RUNS_DIR or ~/.oh-llm/runs).",
    ),
    agent_sdk_path: str | None = typer.Option(
        None,
        "--agent-sdk-path",
        help="Path to agent-sdk checkout (default: $OH_LLM_AGENT_SDK_PATH or ~/repos/agent-sdk).",
    ),
    allow_dirty_sdk: bool = typer.Option(
        False,
        "--allow-dirty-sdk",
        help="Allow creating a worktree from a dirty agent-sdk checkout (unsafe).",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Override safety gating for credential/config failures.",
    ),
    openhands_bin: str = typer.Option(
        "openhands",
        "--openhands-bin",
        help="OpenHands CLI executable (default: openhands on PATH).",
    ),
    redact_env: list[str] = typer.Option(
        [],
        "--redact-env",
        help="Environment variable name to redact from transcript/diff artifacts (repeatable).",
    ),
) -> None:
    """Run an OpenHands agent in an agent-sdk worktree and capture redacted artifacts."""
    cli_ctx = _ctx_with_json_override(ctx, json_output=json_output)
    resolved_runs_dir = Path(runs_dir).expanduser() if runs_dir else resolve_runs_dir()

    try:
        run_dir = resolve_run_dir(resolved_runs_dir, run)
    except (RunNotFoundError, RunAmbiguousError) as exc:
        _emit(cli_ctx, payload={"ok": False, "error": str(exc)}, text=str(exc))
        raise typer.Exit(code=ExitCode.RUN_FAILED)

    record = read_run_record(run_dir)
    if record is None:
        _emit(
            cli_ctx,
            payload={"ok": False, "error": "run.json missing or corrupt", "run_dir": str(run_dir)},
            text=f"run.json missing or corrupt in: {run_dir}",
        )
        raise typer.Exit(code=ExitCode.RUN_FAILED)

    failure = record.get("failure")
    if not isinstance(failure, dict):
        stages = record.get("stages") if isinstance(record.get("stages"), dict) else {}
        failure = failure_from_stages(stages)

    classification = failure.get("classification") if isinstance(failure, dict) else "unknown"
    if classification == "credential_or_config" and not force:
        _emit(
            cli_ctx,
            payload={
                "ok": False,
                "error": "refused",
                "reason": "credential_or_config",
                "run_dir": str(run_dir),
                "failure": failure,
            },
            text=(
                "Refusing to auto-fix a credential/config failure by default. "
                "Fix credentials/config and re-run, or pass --force."
            ),
        )
        raise typer.Exit(code=ExitCode.RUN_FAILED)

    redaction_names = sorted(set([*extract_redact_env(record), *redact_env]))
    redactor = redactor_from_env_vars(*redaction_names)

    try:
        resolved_openhands = resolve_openhands_bin(openhands_bin)
    except OpenHandsError as exc:
        _emit(cli_ctx, payload={"ok": False, "error": str(exc)}, text=str(exc))
        raise typer.Exit(code=ExitCode.RUN_FAILED)

    resolved_sdk_path = resolve_agent_sdk_path(Path(agent_sdk_path) if agent_sdk_path else None)
    artifacts_dir = run_dir / "artifacts"
    try:
        ensured = _autofix_ensure_sdk_worktree(
            artifacts_dir=artifacts_dir,
            record=record,
            resolved_sdk_path=resolved_sdk_path,
            allow_dirty_sdk=allow_dirty_sdk,
        )
    except AgentSdkError as exc:
        _emit(
            cli_ctx,
            payload={"ok": False, "error": str(exc), "run_dir": str(run_dir)},
            text=str(exc),
        )
        raise typer.Exit(code=ExitCode.RUN_FAILED)
    except AutofixWorktreeMissingError as exc:
        _emit(
            cli_ctx,
            payload={
                "ok": False,
                "error": "worktree_missing",
                "worktree_path": str(exc.worktree_path),
            },
            text=str(exc),
        )
        raise typer.Exit(code=ExitCode.RUN_FAILED)

    worktree_path = ensured.worktree_path
    worktree_record = ensured.worktree_record

    # Ensure capsule artifacts exist; use them as context for the OpenHands agent.
    capsule_artifacts = write_capsule_artifacts(
        run_dir=run_dir,
        run_record=record,
        redactor=redactor,
    )

    try:
        artifacts = run_openhands_agent(
            run_dir=run_dir,
            worktree_path=worktree_path,
            capsule_md_path=capsule_artifacts.capsule_md,
            repro_script_path=capsule_artifacts.repro_script,
            worktree_record=worktree_record,
            run_record=record,
            openhands_bin=resolved_openhands,
            redactor=redactor,
        )
    except (OpenHandsError, AgentSdkError, OSError, subprocess.SubprocessError) as exc:
        _emit(
            cli_ctx,
            payload={"ok": False, "error": str(exc), "run_dir": str(run_dir)},
            text=str(exc),
        )
        raise typer.Exit(code=ExitCode.RUN_FAILED)

    _emit(
        cli_ctx,
        payload={
            "ok": True,
            "run_dir": str(run_dir),
            "worktree_path": str(worktree_path),
            "artifacts": {
                "context_md": str(artifacts.context_md),
                "transcript_log": str(artifacts.transcript_log),
                "diff_patch": str(artifacts.diff_patch),
                "run_record_json": str(artifacts.run_record_json),
            },
        },
        text=f"Wrote OpenHands auto-fix artifacts under: {run_dir / 'artifacts'}",
    )
    raise typer.Exit(code=ExitCode.OK)


def _autofix_validate_impl(
    *,
    run_dir: Path,
    record: dict[str, Any],
    redactor: Redactor,
    resolved_sdk_path: Path,
    allow_dirty_sdk: bool,
) -> dict[str, Any]:
    artifacts_dir = run_dir / "artifacts"

    worktree_path = artifacts_dir / "autofix_sdk_worktree"
    try:
        ensured = _autofix_ensure_sdk_worktree(
            artifacts_dir=artifacts_dir,
            record=record,
            resolved_sdk_path=resolved_sdk_path,
            allow_dirty_sdk=allow_dirty_sdk,
        )
    except AgentSdkError as exc:
        return {
            "ok": False,
            "error": str(exc),
            "run_dir": str(run_dir),
            "worktree_path": str(worktree_path),
        }
    except AutofixWorktreeMissingError as exc:
        return {
            "ok": False,
            "error": "worktree_missing",
            "run_dir": str(run_dir),
            "worktree_path": str(exc.worktree_path),
        }

    worktree_path = ensured.worktree_path

    repro_script_path = artifacts_dir / "autofix_repro.py"
    if not repro_script_path.exists():
        repro_script_path = write_capsule_artifacts(
            run_dir=run_dir,
            run_record=record,
            redactor=redactor,
        ).repro_script

    if not repro_script_path.exists():
        return {
            "ok": False,
            "error": "missing_repro_script",
            "run_dir": str(run_dir),
            "worktree_path": str(worktree_path),
            "repro_script": str(repro_script_path),
        }

    created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    result_a = run_repro_stage(
        worktree_path=worktree_path,
        repro_script_path=repro_script_path,
        stage="a",
    )
    payload_a = parse_json_stdout(result_a) or {}
    stage_a_ok = payload_a.get("ok") is True and result_a.exit_code == 0

    result_b = run_repro_stage(
        worktree_path=worktree_path,
        repro_script_path=repro_script_path,
        stage="b",
    )
    payload_b = parse_json_stdout(result_b) or {}
    stage_b_ok = payload_b.get("ok") is True and result_b.exit_code == 0

    stage_a_artifact = artifacts_dir / "autofix_validation_stage_a.json"
    stage_b_artifact = artifacts_dir / "autofix_validation_stage_b.json"

    write_validation_artifact(
        path=stage_a_artifact,
        payload={
            "schema_version": 1,
            "created_at": created_at,
            "stage": "a",
            "ok": stage_a_ok,
            "command_result": result_a.as_json(),
            "stdout_json": payload_a,
        },
        redactor=redactor,
    )
    write_validation_artifact(
        path=stage_b_artifact,
        payload={
            "schema_version": 1,
            "created_at": created_at,
            "stage": "b",
            "ok": stage_b_ok,
            "command_result": result_b.as_json(),
            "stdout_json": payload_b,
        },
        redactor=redactor,
    )

    overall_ok = stage_a_ok and stage_b_ok

    summary_path = artifacts_dir / "autofix_validation.json"
    summary_md_path = artifacts_dir / "autofix_validation.md"
    write_validation_artifact(
        path=summary_path,
        payload={
            "schema_version": 1,
            "created_at": created_at,
            "run_dir": str(run_dir),
            "worktree_path": str(worktree_path),
            "repro_script": str(repro_script_path),
            "ok": overall_ok,
            "stages": {"a": {"ok": stage_a_ok}, "b": {"ok": stage_b_ok}},
            "artifacts": {
                "stage_a": str(stage_a_artifact),
                "stage_b": str(stage_b_artifact),
            },
        },
        redactor=redactor,
    )

    summary_md_path.write_text(
        redactor.redact_text(
            "# oh-llm autofix validation\n\n"
            f"- ok: `{overall_ok}`\n"
            f"- run_dir: `{run_dir}`\n"
            f"- worktree_path: `{worktree_path}`\n"
            f"- repro_script: `{repro_script_path}`\n"
        ),
        encoding="utf-8",
    )
    try:
        summary_md_path.chmod(0o600)
    except OSError:
        pass

    return {
        "ok": overall_ok,
        "run_dir": str(run_dir),
        "worktree_path": str(worktree_path),
        "repro_script": str(repro_script_path),
        "artifacts": {
            "validation_json": str(summary_path),
            "validation_md": str(summary_md_path),
            "stage_a": str(stage_a_artifact),
            "stage_b": str(stage_b_artifact),
        },
    }


@autofix_app.command("validate")
def autofix_validate(
    ctx: typer.Context,
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable JSON output for this command.",
    ),
    run: str = typer.Option(
        ...,
        "--run",
        help="Run id or run directory name/prefix to validate.",
    ),
    runs_dir: str | None = typer.Option(
        None,
        "--runs-dir",
        help="Override runs directory (default: $OH_LLM_RUNS_DIR or ~/.oh-llm/runs).",
    ),
    agent_sdk_path: str | None = typer.Option(
        None,
        "--agent-sdk-path",
        help="Path to agent-sdk checkout (default: $OH_LLM_AGENT_SDK_PATH or ~/repos/agent-sdk).",
    ),
    allow_dirty_sdk: bool = typer.Option(
        False,
        "--allow-dirty-sdk",
        help="Allow creating a worktree from a dirty agent-sdk checkout (unsafe).",
    ),
    redact_env: list[str] = typer.Option(
        [],
        "--redact-env",
        help="Environment variable name to redact from validation artifacts (repeatable).",
    ),
) -> None:
    """Validate a fix in the agent-sdk worktree by running the repro harness."""
    cli_ctx = _ctx_with_json_override(ctx, json_output=json_output)
    resolved_runs_dir = Path(runs_dir).expanduser() if runs_dir else resolve_runs_dir()

    try:
        run_dir = resolve_run_dir(resolved_runs_dir, run)
    except (RunNotFoundError, RunAmbiguousError) as exc:
        _emit(cli_ctx, payload={"ok": False, "error": str(exc)}, text=str(exc))
        raise typer.Exit(code=ExitCode.RUN_FAILED)

    record = read_run_record(run_dir)
    if record is None:
        _emit(
            cli_ctx,
            payload={"ok": False, "error": "run.json missing or corrupt", "run_dir": str(run_dir)},
            text=f"run.json missing or corrupt in: {run_dir}",
        )
        raise typer.Exit(code=ExitCode.RUN_FAILED)

    redaction_names = sorted(set([*extract_redact_env(record), *redact_env]))
    redactor = redactor_from_env_vars(*redaction_names)

    resolved_sdk_path = resolve_agent_sdk_path(Path(agent_sdk_path) if agent_sdk_path else None)
    payload = _autofix_validate_impl(
        run_dir=run_dir,
        record=record,
        redactor=redactor,
        resolved_sdk_path=resolved_sdk_path,
        allow_dirty_sdk=allow_dirty_sdk,
    )

    _emit(
        cli_ctx,
        payload=payload,
        text=f"Wrote validation artifacts under: {run_dir / 'artifacts'}",
    )
    raise typer.Exit(code=ExitCode.OK if payload["ok"] is True else ExitCode.RUN_FAILED)


def _autofix_pr_impl(
    *,
    cli_ctx: CliContext,
    run_dir: Path,
    record: dict[str, Any],
    redactor: Redactor,
    resolved_sdk_path: Path,
    allow_dirty_sdk: bool,
    upstream_repo: str,
    base: str,
    fork_owner: str | None,
    fork_url: str | None,
    push_remote: str,
    title: str | None,
    draft: bool,
    dry_run: bool,
) -> dict[str, Any]:
    artifacts_dir = run_dir / "artifacts"
    pr_record_path = artifacts_dir / "autofix_upstream_pr.json"
    dry_run_record_path = artifacts_dir / "autofix_upstream_pr_dry_run.json"
    worktree_path = artifacts_dir / "autofix_sdk_worktree"
    if pr_record_path.exists():
        try:
            existing = json.loads(pr_record_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = None
        if isinstance(existing, dict):
            pr_obj = existing.get("pr") if isinstance(existing.get("pr"), dict) else {}
            pr_url = pr_obj.get("url")
            if isinstance(pr_url, str) and pr_url.strip():
                return {
                    "url": pr_url.strip(),
                    "existing": True,
                    "worktree_path": str(worktree_path),
                    "artifacts": {
                        "pr_record_json": str(pr_record_path),
                        "pr_body_md": str(artifacts_dir / "autofix_upstream_pr_body.md"),
                    },
                }

    try:
        _autofix_ensure_sdk_worktree(
            artifacts_dir=artifacts_dir,
            record=record,
            resolved_sdk_path=resolved_sdk_path,
            allow_dirty_sdk=allow_dirty_sdk,
        )
    except AgentSdkError as exc:
        _emit(
            cli_ctx,
            payload={"ok": False, "error": str(exc), "run_dir": str(run_dir)},
            text=str(exc),
        )
        raise typer.Exit(code=ExitCode.RUN_FAILED)
    except AutofixWorktreeMissingError as exc:
        _emit(
            cli_ctx,
            payload={
                "ok": False,
                "error": "worktree_missing",
                "worktree_path": str(exc.worktree_path),
            },
            text=str(exc),
        )
        raise typer.Exit(code=ExitCode.RUN_FAILED)

    validation_path = artifacts_dir / "autofix_validation.json"
    if not validation_path.exists():
        _emit(
            cli_ctx,
            payload={"ok": False, "error": "missing_validation", "run_dir": str(run_dir)},
            text=(
                "Missing validation artifacts. Run:\n"
                f"  oh-llm autofix validate --run {run_dir.name}\n"
                "and retry."
            ),
        )
        raise typer.Exit(code=ExitCode.RUN_FAILED)

    try:
        validation = json.loads(validation_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        _emit(
            cli_ctx,
            payload={"ok": False, "error": "invalid_validation_json", "path": str(validation_path)},
            text=f"Invalid JSON: {validation_path}",
        )
        raise typer.Exit(code=ExitCode.RUN_FAILED)

    if validation.get("ok") is not True:
        _emit(
            cli_ctx,
            payload={"ok": False, "error": "validation_failed", "validation": validation},
            text="Validation did not pass; refusing to open an upstream PR.",
        )
        raise typer.Exit(code=ExitCode.RUN_FAILED)

    selection = select_paths_to_commit(worktree_path)
    if not selection.paths:
        _emit(
            cli_ctx,
            payload={
                "ok": False,
                "error": "no_changes",
                "worktree_path": str(worktree_path),
                "selection": selection.as_json(),
            },
            text="No non-ephemeral changes detected in the SDK worktree; nothing to PR.",
        )
        raise typer.Exit(code=ExitCode.RUN_FAILED)

    profile_obj = record.get("profile") if isinstance(record.get("profile"), dict) else {}
    profile_name = str(profile_obj.get("name") or "").strip() or None
    run_id = str(record.get("run_id") or "").strip() or None
    model = str(profile_obj.get("model") or "").strip() or None
    base_url = str(profile_obj.get("base_url") or "").strip() or None

    commit_message = f"oh-llm autofix: {profile_name or model or 'LLM'} ({run_id or run_dir.name})"
    commit_sha = ensure_commit(repo=worktree_path, message=commit_message, selection=selection)
    branch = current_branch(worktree_path)

    if fork_owner:
        owner = fork_owner
    elif dry_run:
        owner = None
    else:
        owner = gh_user_login(worktree_path)

    pr_head = f"{owner}:{branch}" if owner else None
    if fork_url:
        remote_url = fork_url
    elif owner:
        remote_url = f"https://github.com/{owner}/software-agent-sdk.git"
    else:
        remote_url = None

    diffstat = git_show_stat(worktree_path, rev="HEAD")
    body_text = render_pr_body(
        profile_name=profile_name,
        run_id=run_id,
        model=model,
        base_url=base_url,
        validation=validation if isinstance(validation, dict) else {},
        diffstat=diffstat,
        redactor=redactor,
    )
    body_path = artifacts_dir / "autofix_upstream_pr_body.md"
    body_path.parent.mkdir(parents=True, exist_ok=True)
    body_path.write_text(body_text, encoding="utf-8")
    try:
        body_path.chmod(0o600)
    except OSError:
        pass

    pr_title = title or commit_message
    record_path = dry_run_record_path if dry_run else pr_record_path
    result_base: dict[str, Any] = {
        "url": None,
        "existing": False,
        "dry_run": dry_run,
        "worktree_path": str(worktree_path),
        "upstream_repo": upstream_repo,
        "base": base,
        "head": pr_head,
        "title": pr_title,
        "draft": draft,
        "artifacts": {"pr_record_json": str(record_path), "pr_body_md": str(body_path)},
    }

    if dry_run:
        created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        write_validation_artifact(
            path=record_path,
            payload={
                "schema_version": 1,
                "created_at": created_at,
                "run_dir": str(run_dir),
                "worktree_path": str(worktree_path),
                "validation": {"ok": True, "path": str(validation_path)},
                "git": {
                    "branch": branch,
                    "commit": commit_sha,
                    "selection": selection.as_json(),
                },
                "pr": {
                    "dry_run": True,
                    "upstream_repo": upstream_repo,
                    "base": base,
                    "head": pr_head,
                    "title": pr_title,
                    "body_file": str(body_path),
                    "draft": draft,
                },
            },
            redactor=redactor,
        )

        return result_base

    if remote_url is None:
        _emit(
            cli_ctx,
            payload={"ok": False, "error": "missing_fork_owner", "run_dir": str(run_dir)},
            text=(
                "Missing fork owner (required to push PR branch). "
                "Pass --fork-owner or login to gh."
            ),
        )
        raise typer.Exit(code=ExitCode.RUN_FAILED)

    ensure_remote(worktree_path, remote=push_remote, url=remote_url)

    try:
        push_branch(worktree_path, remote=push_remote, branch=branch)
    except AgentSdkError as exc:
        _emit(
            cli_ctx,
            payload={
                "ok": False,
                "error": str(exc),
                "worktree_path": str(worktree_path),
                "branch": branch,
                "remote": {"name": push_remote, "url": remote_url},
            },
            text=(
                "Failed to push branch. You can retry manually:\n"
                f"  git -C {worktree_path} push -u {push_remote} {branch}\n"
                f"  gh pr create --repo {upstream_repo} --base {base} --head {owner}:{branch}\n"
            ),
        )
        raise typer.Exit(code=ExitCode.RUN_FAILED)

    try:
        pr_url = gh_pr_create(
            repo=worktree_path,
            upstream_repo=upstream_repo,
            base=base,
            head=pr_head,
            title=pr_title,
            body_file=body_path,
            draft=draft,
        )
    except AgentSdkError as exc:
        _emit(
            cli_ctx,
            payload={
                "ok": False,
                "error": str(exc),
                "worktree_path": str(worktree_path),
                "branch": branch,
                "commit": commit_sha,
                "body_file": str(body_path),
                "head": pr_head,
            },
            text=(
                "Failed to create upstream PR. You can retry manually:\n"
                f"  gh pr create --repo {upstream_repo} --base {base} --head {pr_head} "
                f"--title {json.dumps(pr_title)} --body-file {body_path}\n"
            ),
        )
        raise typer.Exit(code=ExitCode.RUN_FAILED)

    created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    write_validation_artifact(
        path=pr_record_path,
        payload={
            "schema_version": 1,
            "created_at": created_at,
            "run_dir": str(run_dir),
            "worktree_path": str(worktree_path),
            "validation": {"ok": True, "path": str(validation_path)},
            "git": {
                "branch": branch,
                "commit": commit_sha,
                "push_remote": {"name": push_remote, "url": remote_url},
                "selection": selection.as_json(),
            },
            "pr": {
                "url": pr_url,
                "upstream_repo": upstream_repo,
                "base": base,
                "head": pr_head,
                "title": pr_title,
                "body_file": str(body_path),
                "draft": draft,
            },
        },
        redactor=redactor,
    )

    result = dict(result_base)
    result["url"] = pr_url
    return result


@autofix_app.command("pr")
def autofix_pr(
    ctx: typer.Context,
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable JSON output for this command.",
    ),
    run: str = typer.Option(
        ...,
        "--run",
        help="Run id or run directory name/prefix to open an upstream PR for.",
    ),
    runs_dir: str | None = typer.Option(
        None,
        "--runs-dir",
        help="Override runs directory (default: $OH_LLM_RUNS_DIR or ~/.oh-llm/runs).",
    ),
    agent_sdk_path: str | None = typer.Option(
        None,
        "--agent-sdk-path",
        help="Path to agent-sdk checkout (default: $OH_LLM_AGENT_SDK_PATH or ~/repos/agent-sdk).",
    ),
    allow_dirty_sdk: bool = typer.Option(
        False,
        "--allow-dirty-sdk",
        help="Allow creating a worktree from a dirty agent-sdk checkout (unsafe).",
    ),
    upstream_repo: str = typer.Option(
        "OpenHands/software-agent-sdk",
        "--upstream-repo",
        help="Upstream repo to open the PR against (owner/name).",
    ),
    base: str = typer.Option(
        "main",
        "--base",
        help="Base branch in the upstream repo.",
    ),
    fork_owner: str | None = typer.Option(
        None,
        "--fork-owner",
        help="Fork owner for the PR head (default: `gh api user --jq .login`).",
    ),
    fork_url: str | None = typer.Option(
        None,
        "--fork-url",
        help=(
            "Fork remote URL to push to (default: "
            "https://github.com/<fork-owner>/software-agent-sdk.git)."
        ),
    ),
    push_remote: str = typer.Option(
        "fork",
        "--push-remote",
        help="Git remote name to push the worktree branch to (default: fork).",
    ),
    title: str | None = typer.Option(
        None,
        "--title",
        help="Override PR title.",
    ),
    draft: bool = typer.Option(
        False,
        "--draft",
        help="Create PR as a draft.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Prepare PR artifacts but do not push or create a PR.",
    ),
    redact_env: list[str] = typer.Option(
        [],
        "--redact-env",
        help="Environment variable name to redact from generated PR artifacts (repeatable).",
    ),
) -> None:
    """Open an upstream PR for fixes made in the agent-sdk worktree."""
    cli_ctx = _ctx_with_json_override(ctx, json_output=json_output)
    resolved_runs_dir = Path(runs_dir).expanduser() if runs_dir else resolve_runs_dir()

    try:
        run_dir = resolve_run_dir(resolved_runs_dir, run)
    except (RunNotFoundError, RunAmbiguousError) as exc:
        _emit(cli_ctx, payload={"ok": False, "error": str(exc)}, text=str(exc))
        raise typer.Exit(code=ExitCode.RUN_FAILED)

    record = read_run_record(run_dir)
    if record is None:
        _emit(
            cli_ctx,
            payload={"ok": False, "error": "run.json missing or corrupt", "run_dir": str(run_dir)},
            text=f"run.json missing or corrupt in: {run_dir}",
        )
        raise typer.Exit(code=ExitCode.RUN_FAILED)

    redaction_names = sorted(set([*extract_redact_env(record), *redact_env]))
    redactor = redactor_from_env_vars(*redaction_names)

    resolved_sdk_path = resolve_agent_sdk_path(Path(agent_sdk_path) if agent_sdk_path else None)
    pr_payload = _autofix_pr_impl(
        cli_ctx=cli_ctx,
        run_dir=run_dir,
        record=record,
        redactor=redactor,
        resolved_sdk_path=resolved_sdk_path,
        allow_dirty_sdk=allow_dirty_sdk,
        upstream_repo=upstream_repo,
        base=base,
        fork_owner=fork_owner,
        fork_url=fork_url,
        push_remote=push_remote,
        title=title,
        draft=draft,
        dry_run=dry_run,
    )

    artifacts_value = pr_payload.get("artifacts")
    pr_artifacts = artifacts_value if isinstance(artifacts_value, dict) else {}
    _emit(
        cli_ctx,
        payload={
            "ok": True,
            "run_dir": str(run_dir),
            "worktree_path": pr_payload.get("worktree_path"),
            "pr_url": pr_payload.get("url"),
            "artifacts": pr_artifacts,
            "dry_run": pr_payload.get("dry_run") is True,
        },
        text=(
            "Dry-run: prepared upstream PR artifacts (no push, no PR created)."
            if pr_payload.get("dry_run") is True
            else f"Created upstream PR: {pr_payload.get('url')}"
        ),
    )
    raise typer.Exit(code=ExitCode.OK)

@app.command()
def tui(
    ctx: typer.Context,
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable JSON output for this command.",
    ),
) -> None:
    """Start the interactive TUI (stub)."""
    cli_ctx = _ctx_with_json_override(ctx, json_output=json_output)
    _emit(
        cli_ctx,
        payload={"ok": False, "error": "not_implemented"},
        text="TUI not implemented yet.",
    )
    raise typer.Exit(code=ExitCode.INTERNAL_ERROR)


@sdk_app.command("info")
def sdk_info(
    ctx: typer.Context,
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable JSON output for this command.",
    ),
    path: str | None = typer.Option(
        None,
        "--path",
        help=(
            "Path to the local agent-sdk checkout "
            "(default: $OH_LLM_AGENT_SDK_PATH or ~/repos/agent-sdk)."
        ),
    ),
) -> None:
    """Show basic info about the SDK checkout used by oh-llm."""
    cli_ctx = _ctx_with_json_override(ctx, json_output=json_output)

    agent_sdk_path = resolve_agent_sdk_path(Path(path) if path else None)
    info = collect_agent_sdk_info(agent_sdk_path)

    lines = [f"agent-sdk path: {info.path}"]
    if info.git_sha:
        dirty = " (dirty)" if info.git_dirty else ""
        lines.append(f"git sha: {info.git_sha}{dirty}")
    else:
        lines.append("git sha: (unavailable)")
    lines.append(f"uv available: {info.uv_available}")

    _emit(cli_ctx, payload=info.as_json(), text="\n".join(lines))


@sdk_app.command("status")
def sdk_status(
    ctx: typer.Context,
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable JSON output for this command.",
    ),
    path: str | None = typer.Option(
        None,
        "--path",
        help=(
            "Path to the local agent-sdk checkout "
            "(default: $OH_LLM_AGENT_SDK_PATH or ~/repos/agent-sdk)."
        ),
    ),
) -> None:
    """Check SDK checkout status (exists + git SHA + dirty)."""
    cli_ctx = _ctx_with_json_override(ctx, json_output=json_output)
    agent_sdk_path = resolve_agent_sdk_path(Path(path) if path else None)

    if not agent_sdk_path.exists():
        payload = {
            "ok": False,
            "sdk_path": str(agent_sdk_path),
            "git_sha": None,
            "dirty": None,
            "error": "missing_path",
            "hint": (
                "Clone OpenHands/software-agent-sdk to ~/repos/agent-sdk, "
                "or set $OH_LLM_AGENT_SDK_PATH."
            ),
        }
        _emit(cli_ctx, payload=payload, text=f"agent-sdk not found: {agent_sdk_path}")
        raise typer.Exit(code=ExitCode.RUN_FAILED)

    if not is_git_repo(agent_sdk_path):
        payload = {
            "ok": False,
            "sdk_path": str(agent_sdk_path),
            "git_sha": None,
            "dirty": None,
            "error": "not_git_repo",
            "hint": "The agent-sdk path must be a git checkout (expected a repo root).",
        }
        _emit(cli_ctx, payload=payload, text=f"agent-sdk is not a git repo: {agent_sdk_path}")
        raise typer.Exit(code=ExitCode.RUN_FAILED)

    info = collect_agent_sdk_info(agent_sdk_path)
    payload = {
        "ok": True,
        "sdk_path": str(info.path),
        "git_sha": info.git_sha,
        "dirty": info.git_dirty,
    }
    dirty = " (dirty)" if info.git_dirty else ""
    text = f"agent-sdk OK: {info.path}\nsha: {info.git_sha}{dirty}"
    _emit(cli_ctx, payload=payload, text=text)


@sdk_app.command("check-import")
def sdk_check_import(
    ctx: typer.Context,
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable JSON output for this command.",
    ),
    path: str | None = typer.Option(
        None,
        "--path",
        help=(
            "Path to the local agent-sdk checkout "
            "(default: $OH_LLM_AGENT_SDK_PATH or ~/repos/agent-sdk)."
        ),
    ),
) -> None:
    """Verify we can import openhands SDK from the configured agent-sdk workspace."""
    cli_ctx = _ctx_with_json_override(ctx, json_output=json_output)
    agent_sdk_path = resolve_agent_sdk_path(Path(path) if path else None)

    try:
        proc = uv_run_python(
            agent_sdk_path=agent_sdk_path,
            python_args=[
                "-c",
                "import json; import openhands.sdk; "
                "print(json.dumps({'ok': True, 'module_file': openhands.sdk.__file__}))",
            ],
        )
    except AgentSdkError as exc:
        _emit(cli_ctx, payload={"ok": False, "error": str(exc)}, text=str(exc))
        raise typer.Exit(code=ExitCode.RUN_FAILED)

    if proc.returncode != 0:
        _emit(
            cli_ctx,
            payload={"ok": False, "stdout": proc.stdout, "stderr": proc.stderr},
            text=(proc.stderr or proc.stdout or "Failed to import SDK."),
        )
        raise typer.Exit(code=ExitCode.RUN_FAILED)

    try:
        result = json.loads(proc.stdout.strip().splitlines()[-1])
        module_file = result["module_file"]
    except (json.JSONDecodeError, IndexError, KeyError, TypeError):
        module_file = None

    _emit(
        cli_ctx,
        payload={
            "ok": True,
            "module_file": module_file,
            "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip(),
        },
        text=f"SDK import OK: {module_file}" if module_file else "SDK import OK.",
    )


app.add_typer(profile_app, name="profile", help="Manage LLM profiles.")
app.add_typer(runs_app, name="runs", help="View past runs.")
app.add_typer(autofix_app, name="autofix", help="Auto-fix failing models (agent).")
app.add_typer(sdk_app, name="sdk", help="SDK integration helpers.")


def main() -> None:
    app()
