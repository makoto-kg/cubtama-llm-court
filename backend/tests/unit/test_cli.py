from pathlib import Path

import pytest
from typer.testing import CliRunner

from llm_court.cli.main import app
from llm_court.llm.client import BackendFactory
from tests.fakes import FakeChatBackend, FakeError, FakeResponse

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


def _factory(fake: FakeChatBackend) -> BackendFactory:
    return lambda _provider: fake


def test_bench_with_fake_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    from llm_court.cli import main as cli_main
    from tests.unit.test_bench import bench_responder

    fake = FakeChatBackend(responder=bench_responder)
    monkeypatch.setattr(cli_main, "backend_factory", _factory(fake))
    monkeypatch.setenv("COLUMNS", "200")  # 表が切り詰められないように
    monkeypatch.setenv("LLM_COURT_MODELS_CONFIG_PATH", str(BACKEND_ROOT / "config/models.yaml"))
    monkeypatch.setenv("LLM_COURT_PROMPTS_DIR", str(BACKEND_ROOT / "prompts"))
    result = runner.invoke(app, ["bench", "--n", "1", "--role", "debater"])
    assert result.exit_code == 0, result.output
    assert "LLM ベンチマーク" in result.output
    assert "構造化出力" in result.output
    assert "1/1 (100%)" in result.output
    assert len(fake.requests) == 2


def test_bench_connection_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from llm_court.cli import main as cli_main

    fake = FakeChatBackend(
        responder=lambda _r: FakeResponse(error=FakeError(kind="connection", message="down"))
    )
    monkeypatch.setattr(cli_main, "backend_factory", _factory(fake))
    monkeypatch.setenv("LLM_COURT_MODELS_CONFIG_PATH", str(BACKEND_ROOT / "config/models.yaml"))
    monkeypatch.setenv("LLM_COURT_PROMPTS_DIR", str(BACKEND_ROOT / "prompts"))
    result = runner.invoke(app, ["bench", "--n", "1", "--role", "debater"])
    assert result.exit_code == 1
    assert "接続エラー" in result.output
