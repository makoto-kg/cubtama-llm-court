"""評価仕様ファイル(YAML)。"""

from pathlib import Path
from typing import Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class EvalSpecError(Exception):
    """評価仕様ファイルの読み込み・検証に失敗した。"""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EvalConfig(_Strict):
    """比較するモデル構成。`models` は models.yaml 形式のファイル。"""

    name: str = Field(min_length=1)
    models: Path


class EvalTopic(_Strict):
    """評価に使うテーマと、固定で使う捜査結果(`llm-court research` の JSON)。"""

    topic: str = Field(min_length=1)
    evidence: Path


class EvalSpec(_Strict):
    name: str = Field(min_length=1)
    rounds: int = Field(default=1, ge=1)
    runs: int = Field(default=1, ge=1)
    """テーマごとのディベートの回数。"""
    judge_repeats: int = Field(default=2, ge=0)
    """終わったディベートを裁判長に追加で評価させる回数(毎回 2 つの提示順で評価する)。"""
    analyst: bool = False
    """分析官の候補精度も評価する(反論・最終弁論の各発言に対して候補を作り、検証役が判定する)。"""
    configs: list[EvalConfig] = Field(min_length=1)
    topics: list[EvalTopic] = Field(min_length=1)
    reference_judge: Path | None = None
    """参照用裁判長(models.yaml 形式)。指定すると、その judge 役で全ディベートを採点し直す。"""

    @model_validator(mode="after")
    def _unique_names(self) -> Self:
        names = [c.name for c in self.configs]
        duplicates = sorted({n for n in names if names.count(n) > 1})
        if duplicates:
            raise ValueError(f"構成名が重複しています: {duplicates}")
        return self

    def referenced_files(self) -> list[Path]:
        files = [c.models for c in self.configs] + [t.evidence for t in self.topics]
        if self.reference_judge is not None:
            files.append(self.reference_judge)
        return files


def load_spec(path: Path) -> EvalSpec:
    """仕様を読み込んで検証する。中のパスは実行時の作業ディレクトリ基準。"""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        spec = EvalSpec.model_validate(raw)
    except OSError as e:
        raise EvalSpecError(f"{path} を読み込めません: {e}") from e
    except (yaml.YAMLError, ValidationError) as e:
        raise EvalSpecError(f"{path} の内容が不正です:\n{e}") from e
    missing = [str(f) for f in spec.referenced_files() if not f.exists()]
    if missing:
        raise EvalSpecError(f"{path} が参照するファイルがありません: {', '.join(missing)}")
    return spec
