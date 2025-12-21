from typer.testing import CliRunner

from oh_llm.cli import ExitCode, app


def test_cli_help_smoke() -> None:
    runner = CliRunner()

    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0

    result = runner.invoke(app, ["profile", "--help"])
    assert result.exit_code == 0

    result = runner.invoke(app, ["run", "--help"])
    assert result.exit_code == 0


def test_cli_run_is_nonzero_until_implemented() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["run"])
    assert result.exit_code == ExitCode.INTERNAL_ERROR
