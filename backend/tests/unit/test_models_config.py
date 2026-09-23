from pathlib import Path
from typing import Any

import pytest
import yaml

from llm_court.config import ConfigError, Role, load_models_config

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _base_config() -> dict[str, Any]:
    return {
        "providers": {
            "local": {
                "base_url": "http://localhost:1234/v1",
                "capabilities": {"json_schema": True, "streaming": True},
                "max_concurrency": 2,
            }
        },
        "models": {
            "heavy": {"provider": "local", "model": "big", "reasoning": "high"},
            "fast": {"provider": "local", "model": "small", "reasoning": "low"},
        },
        "roles": {role.value: ("fast" if role is Role.DEBATER else "heavy") for role in Role},
    }


def _write(tmp_path: Path, data: dict[str, Any]) -> Path:
    path = tmp_path / "models.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def test_bundled_models_yaml_is_valid() -> None:
    config = load_models_config(BACKEND_ROOT / "config" / "models.yaml")
    assert set(config.roles) == set(Role)
    # 論者と裁判長は別モデル(自己選好バイアス対策)
    assert config.roles[Role.DEBATER] != config.roles[Role.JUDGE]


def test_resolve_returns_model_and_provider(tmp_path: Path) -> None:
    config = load_models_config(_write(tmp_path, _base_config()))
    resolved = config.resolve(Role.DEBATER)
    assert resolved.model_key == "fast"
    assert resolved.model.model == "small"
    assert resolved.provider_key == "local"
    assert resolved.provider.capabilities.json_schema is True
    assert resolved.provider.capabilities.tool_calling is False
    assert resolved.provider.api_key.get_secret_value() == "not-needed"


def test_unknown_provider_is_rejected(tmp_path: Path) -> None:
    data = _base_config()
    data["models"]["heavy"]["provider"] = "missing"
    with pytest.raises(ConfigError, match="未定義の provider 'missing'"):
        load_models_config(_write(tmp_path, data))


def test_unknown_model_is_rejected(tmp_path: Path) -> None:
    data = _base_config()
    data["roles"]["judge"] = "missing"
    with pytest.raises(ConfigError, match="未定義の model 'missing'"):
        load_models_config(_write(tmp_path, data))


def test_missing_role_is_rejected(tmp_path: Path) -> None:
    data = _base_config()
    del data["roles"]["witness"]
    with pytest.raises(ConfigError, match="witness"):
        load_models_config(_write(tmp_path, data))


def test_unknown_role_is_rejected(tmp_path: Path) -> None:
    data = _base_config()
    data["roles"]["narrator"] = "fast"
    with pytest.raises(ConfigError):
        load_models_config(_write(tmp_path, data))


def test_unknown_field_is_rejected(tmp_path: Path) -> None:
    data = _base_config()
    data["models"]["fast"]["temprature"] = 0.5
    with pytest.raises(ConfigError):
        load_models_config(_write(tmp_path, data))


def test_env_var_is_expanded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_LLM_KEY", "secret-123")
    data = _base_config()
    data["providers"]["local"]["api_key"] = "${TEST_LLM_KEY}"
    config = load_models_config(_write(tmp_path, data))
    assert config.providers["local"].api_key.get_secret_value() == "secret-123"
    assert "secret-123" not in repr(config)


def test_missing_env_var_is_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TEST_LLM_KEY", raising=False)
    data = _base_config()
    data["providers"]["local"]["api_key"] = "${TEST_LLM_KEY}"
    with pytest.raises(ConfigError, match="TEST_LLM_KEY"):
        load_models_config(_write(tmp_path, data))


def test_missing_file_is_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_models_config(tmp_path / "nope.yaml")
