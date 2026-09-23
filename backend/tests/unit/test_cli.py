from pathlib import Path

from typer.testing import CliRunner

from llm_court.cli.main import app

BACKEND_ROOT = Path(__file__).resolve().parents[2]
runner = CliRunner()


def test_help() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "config" in result.output


def test_config_check_ok() -> None:
    result = runner.invoke(
        app, ["config", "check", "--path", str(BACKEND_ROOT / "config" / "models.yaml")]
    )
    assert result.exit_code == 0, result.output
    assert "OK" in result.output


def test_config_check_error(tmp_path: Path) -> None:
    bad = tmp_path / "models.yaml"
    bad.write_text("providers: {}\nmodels: {}\nroles: {}\n", encoding="utf-8")
    result = runner.invoke(app, ["config", "check", "--path", str(bad)])
    assert result.exit_code == 1
    assert "設定エラー" in result.output
