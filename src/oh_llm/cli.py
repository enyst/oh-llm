from __future__ import annotations

import json
from dataclasses import dataclass
from enum import IntEnum
from typing import Any

import typer

from oh_llm import __version__


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
def run(ctx: typer.Context) -> None:
    """Run the compatibility suite for a configured LLM (stub)."""
    cli_ctx = _ctx(ctx)
    _emit(
        cli_ctx,
        payload={"ok": False, "error": "not_implemented"},
        text="Run runner not implemented yet. See PRD.md (Stage A/B).",
    )
    raise typer.Exit(code=ExitCode.INTERNAL_ERROR)


@profile_app.command("list")
def profile_list(ctx: typer.Context) -> None:
    """List known LLM profiles (stub)."""
    cli_ctx = _ctx(ctx)
    _emit(cli_ctx, payload={"profiles": []}, text="No profiles yet (stub).")


@profile_app.command("create")
def profile_create(ctx: typer.Context) -> None:
    """Create an LLM profile (stub)."""
    cli_ctx = _ctx(ctx)
    _emit(
        cli_ctx,
        payload={"ok": False, "error": "not_implemented"},
        text="Profile creation not implemented yet. (Planned: reuse SDK LLMRegistry.)",
    )
    raise typer.Exit(code=ExitCode.INTERNAL_ERROR)


@runs_app.command("list")
def runs_list(ctx: typer.Context) -> None:
    """List previous runs (stub)."""
    cli_ctx = _ctx(ctx)
    _emit(cli_ctx, payload={"runs": []}, text="No runs yet (stub).")


@autofix_app.command("start")
def autofix_start(ctx: typer.Context) -> None:
    """Start an auto-fix agent run (stub)."""
    cli_ctx = _ctx(ctx)
    _emit(
        cli_ctx,
        payload={"ok": False, "error": "not_implemented"},
        text="Auto-fix not implemented yet.",
    )
    raise typer.Exit(code=ExitCode.INTERNAL_ERROR)


@app.command()
def tui(ctx: typer.Context) -> None:
    """Start the interactive TUI (stub)."""
    cli_ctx = _ctx(ctx)
    _emit(
        cli_ctx,
        payload={"ok": False, "error": "not_implemented"},
        text="TUI not implemented yet.",
    )
    raise typer.Exit(code=ExitCode.INTERNAL_ERROR)


app.add_typer(profile_app, name="profile", help="Manage LLM profiles.")
app.add_typer(runs_app, name="runs", help="View past runs.")
app.add_typer(autofix_app, name="autofix", help="Auto-fix failing models (agent).")


def main() -> None:
    app()
