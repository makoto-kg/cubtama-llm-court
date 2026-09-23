"""`config/models.yaml` のスキーマと読み込み。

コードは役割名で LLM を呼び、どのプロバイダ・モデルを使うかはこのファイルで決める。
"""

import os
import re
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, model_validator


class ConfigError(Exception):
    """設定ファイルの読み込み・検証に失敗した。"""


class Role(StrEnum):
    """LLM の役割。"""

    RESEARCHER = "researcher"
    DEBATER = "debater"
    CLAIM_EXTRACTOR = "claim_extractor"
    ANALYST = "analyst"
    ADVOCATE = "advocate"
    JUDGE = "judge"
    SCENARIO_WRITER = "scenario_writer"
    WITNESS = "witness"
    SOLVER = "solver"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Capabilities(_Strict):
    """プロバイダが対応する機能。呼び出し側はこれを見て分岐する。"""

    json_schema: bool = False
    tool_calling: bool = False
    streaming: bool = False


class ProviderConfig(_Strict):
    """OpenAI 互換 API のエンドポイント。"""

    base_url: str
    api_key: SecretStr = SecretStr("not-needed")
    capabilities: Capabilities = Capabilities()
    max_concurrency: int = Field(default=1, ge=1)


class ModelConfig(_Strict):
    """プロバイダ上のモデルと呼び出しパラメータ。"""

    provider: str
    model: str
    reasoning: Literal["low", "medium", "high"] | None = None


class ResolvedModel(_Strict):
    """役割から解決したモデルとプロバイダ。"""

    role: Role
    model_key: str
    model: ModelConfig
    provider_key: str
    provider: ProviderConfig


class ModelsConfig(_Strict):
    """`models.yaml` 全体。"""

    providers: dict[str, ProviderConfig]
    models: dict[str, ModelConfig]
    roles: dict[Role, str]

    @model_validator(mode="after")
    def _check_references(self) -> Self:
        errors: list[str] = []
        for key, model in self.models.items():
            if model.provider not in self.providers:
                errors.append(f"models.{key}: 未定義の provider '{model.provider}'")
        missing = [role.value for role in Role if role not in self.roles]
        if missing:
            errors.append(f"roles: 割り当てのない役割 {missing}")
        for role, model_key in self.roles.items():
            if model_key not in self.models:
                errors.append(f"roles.{role.value}: 未定義の model '{model_key}'")
        if errors:
            raise ValueError("; ".join(errors))
        return self

    def resolve(self, role: Role) -> ResolvedModel:
        """役割に割り当てられたモデルとプロバイダを返す。"""
        model_key = self.roles[role]
        model = self.models[model_key]
        return ResolvedModel(
            role=role,
            model_key=model_key,
            model=model,
            provider_key=model.provider,
            provider=self.providers[model.provider],
        )


_ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _expand_env(value: Any) -> Any:
    """文字列中の `${VAR}` を環境変数で展開する(秘密情報を YAML に書かないため)。"""
    if isinstance(value, str):

        def replace(match: re.Match[str]) -> str:
            name = match.group(1)
            if name not in os.environ:
                raise ConfigError(f"環境変数 {name} が設定されていません")
            return os.environ[name]

        return _ENV_REF.sub(replace, value)
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}  # pyright: ignore[reportUnknownVariableType]
    if isinstance(value, list):
        return [_expand_env(v) for v in value]  # pyright: ignore[reportUnknownVariableType]
    return value


def load_models_config(path: Path) -> ModelsConfig:
    """`models.yaml` を読み込み、検証済みの設定を返す。"""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as e:
        raise ConfigError(f"{path} を読み込めません: {e}") from e
    except yaml.YAMLError as e:
        raise ConfigError(f"{path} の YAML が不正です: {e}") from e
    try:
        return ModelsConfig.model_validate(_expand_env(raw))
    except ValidationError as e:
        raise ConfigError(f"{path} の内容が不正です:\n{e}") from e
