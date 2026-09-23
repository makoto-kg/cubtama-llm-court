from pathlib import Path

import pytest

from llm_court.config import Settings


def test_defaults(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)  # 作業ディレクトリの .env を読ませない
    settings = Settings()
    assert settings.models_config_path == Path("config/models.yaml")
    assert settings.searxng_url == "http://localhost:8080"


def test_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LLM_COURT_SEARXNG_URL", "http://searx:9999")
    monkeypatch.setenv("LLM_COURT_MODELS_CONFIG_PATH", "/etc/models.yaml")
    settings = Settings()
    assert settings.searxng_url == "http://searx:9999"
    assert settings.models_config_path == Path("/etc/models.yaml")


def test_nested_research_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LLM_COURT_RESEARCH__MAX_CHARS_PER_PAGE", "12000")
    assert Settings().research.max_chars_per_page == 12000
