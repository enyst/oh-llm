from __future__ import annotations

import json
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
) -> None:
    """Run the compatibility suite for a configured LLM (stub)."""
    cli_ctx = _ctx_with_json_override(ctx, json_output=json_output)
    _emit(
        cli_ctx,
        payload={"ok": False, "error": "not_implemented"},
        text="Run runner not implemented yet. See PRD.md (Stage A/B).",
    )
    raise typer.Exit(code=ExitCode.INTERNAL_ERROR)


@profile_app.command("list")
def profile_list(
    ctx: typer.Context,
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable JSON output for this command.",
    ),
) -> None:
    """List known LLM profiles (stub)."""
    cli_ctx = _ctx_with_json_override(ctx, json_output=json_output)
    _emit(cli_ctx, payload={"profiles": []}, text="No profiles yet (stub).")


@profile_app.command("create")
def profile_create(
    ctx: typer.Context,
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable JSON output for this command.",
    ),
) -> None:
    """Create an LLM profile (stub)."""
    cli_ctx = _ctx_with_json_override(ctx, json_output=json_output)
    _emit(
        cli_ctx,
        payload={"ok": False, "error": "not_implemented"},
        text="Profile creation not implemented yet. (Planned: reuse SDK LLMRegistry.)",
    )
    raise typer.Exit(code=ExitCode.INTERNAL_ERROR)


@runs_app.command("list")
def runs_list(
    ctx: typer.Context,
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable JSON output for this command.",
    ),
) -> None:
    """List previous runs (stub)."""
    cli_ctx = _ctx_with_json_override(ctx, json_output=json_output)
    _emit(cli_ctx, payload={"runs": []}, text="No runs yet (stub).")


@autofix_app.command("start")
def autofix_start(
    ctx: typer.Context,
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable JSON output for this command.",
    ),
) -> None:
    """Start an auto-fix agent run (stub)."""
    cli_ctx = _ctx_with_json_override(ctx, json_output=json_output)
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
