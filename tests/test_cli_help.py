from pathlib import Path

import pytest
from typer.testing import CliRunner

from oh_llm.cli import ExitCode, app

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "args",
    [
        ["--help"],
        ["run", "--help"],
        ["profile", "--help"],
        ["profile", "list", "--help"],
        ["profile", "add", "--help"],
        ["profile", "create", "--help"],
        ["profile", "show", "--help"],
        ["runs", "--help"],
        ["runs", "list", "--help"],
        ["autofix", "--help"],
        ["autofix", "start", "--help"],
        ["sdk", "--help"],
        ["sdk", "info", "--help"],
        ["sdk", "check-import", "--help"],
        ["tui", "--help"],
    ],
)
def test_cli_help_smoke(args: list[str]) -> None:
    runner = CliRunner()
    result = runner.invoke(app, args)
    assert result.exit_code == 0


@pytest.mark.parametrize(
    "args",
    [
        ["run"],
        ["autofix", "start"],
        ["tui"],
    ],
)
def test_stub_commands_fail_until_implemented(args: list[str], tmp_path: Path) -> None:
    runner = CliRunner()
    invoked_args = list(args)
    if invoked_args == ["run"]:
        invoked_args.extend(["--runs-dir", str(tmp_path / "runs")])

    result = runner.invoke(app, invoked_args)
    assert result.exit_code == ExitCode.INTERNAL_ERROR
    assert "not implemented" in result.stdout.lower()


@pytest.mark.parametrize(
    "args",
    [
        ["profile", "list"],
        ["runs", "list"],
    ],
)
def test_stub_list_commands_succeed(args: list[str]) -> None:
    runner = CliRunner()
    result = runner.invoke(app, args)
    assert result.exit_code == ExitCode.OK
