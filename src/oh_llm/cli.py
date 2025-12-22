from __future__ import annotations

import json
import os
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Any

import typer

from oh_llm import __version__
from oh_llm.agent_sdk import (
    AgentSdkError,
    collect_agent_sdk_info,
    resolve_agent_sdk_path,
    uv_run_python,
)
from oh_llm.failures import failure_from_stages, update_run_failure
from oh_llm.profiles import get_profile, list_profiles, upsert_profile
from oh_llm.redaction import redactor_from_env_vars
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


class ExitCode(IntEnum):
    OK = 0
    INTERNAL_ERROR = 1
    RUN_FAILED = 2


@dataclass(frozen=True)
class CliContext:
    json_output: bool


app = typer.Typer(no_args_is_help=True, add_completion=False)
profile_app = typer.Typer(no_args_is_help=True)
runs_app = typer.Typer(no_args_is_help=True)
autofix_app = typer.Typer(no_args_is_help=True)
sdk_app = typer.Typer(no_args_is_help=True)


def _ctx(ctx: typer.Context) -> CliContext:
    obj = ctx.obj
    if isinstance(obj, CliContext):
        return obj
    return CliContext(json_output=False)


def _emit(ctx: CliContext, *, payload: dict[str, Any], text: str) -> None:
    if ctx.json_output:
        typer.echo(json.dumps(payload, sort_keys=True))
        return
    typer.echo(text)


def _ctx_with_json_override(ctx: typer.Context, *, json_output: bool) -> CliContext:
    base = _ctx(ctx)
    if json_output:
        return CliContext(json_output=True)
    return base


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

    ctx.obj = CliContext(json_output=json_output)


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
    force: bool = typer.Option(
        False,
        "--force",
        help="Override safety gating for credential/config failures.",
    ),
) -> None:
    """Start an auto-fix agent run (stub)."""
    cli_ctx = _ctx_with_json_override(ctx, json_output=json_output)

    if run:
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
                payload={
                    "ok": False,
                    "error": "run.json missing or corrupt",
                    "run_dir": str(run_dir),
                },
                text=f"run.json missing or corrupt in: {run_dir}",
            )
            raise typer.Exit(code=ExitCode.RUN_FAILED)

        failure = record.get("failure")
        if not isinstance(failure, dict):
            stages = record.get("stages") if isinstance(record.get("stages"), dict) else {}
            failure = failure_from_stages(stages)

        classification = (
            failure.get("classification") if isinstance(failure, dict) else "unknown"
        )

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

        _emit(
            cli_ctx,
            payload={
                "ok": False,
                "error": "not_implemented",
                "run_dir": str(run_dir),
                "failure": failure,
            },
            text="Auto-fix not implemented yet.",
        )
        raise typer.Exit(code=ExitCode.INTERNAL_ERROR)

    _emit(
        cli_ctx,
        payload={"ok": False, "error": "not_implemented"},
        text="Auto-fix not implemented yet.",
    )
    raise typer.Exit(code=ExitCode.INTERNAL_ERROR)


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
