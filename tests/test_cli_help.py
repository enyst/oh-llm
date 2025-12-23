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
        ["runs", "show", "--help"],
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
        ["tui"],
    ],
)
def test_stub_commands_fail_until_implemented(args: list[str], tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, list(args))
    assert result.exit_code == ExitCode.INTERNAL_ERROR
    assert "not implemented" in result.stdout.lower()


def test_run_requires_profile(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["run", "--runs-dir", str(tmp_path / "runs")])
    assert result.exit_code == ExitCode.RUN_FAILED
    assert "profile" in result.stdout.lower()


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
