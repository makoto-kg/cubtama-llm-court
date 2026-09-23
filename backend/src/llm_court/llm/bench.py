"""各役割のモデルの速度と構造化出力の成功率を測るベンチマーク。"""

import statistics
from collections import Counter
from collections.abc import Callable, Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from llm_court.config import Role
from llm_court.llm.client import LLMClient
from llm_court.llm.errors import LLMConnectionError, LLMError
from llm_court.llm.metrics import InMemoryRecorder, LLMCallRecord
from llm_court.llm.prompts import PromptLoader

BENCH_TOPICS: tuple[tuple[str, str], ...] = (
    ("リモートワークは生産性を高める", "賛成"),
    ("小学校の英語教育は早く始めるほどよい", "反対"),
    ("原子力発電を拡大すべきだ", "賛成"),
    ("大学入試から学力試験をなくすべきだ", "反対"),
)

BenchTask = Literal["text", "structured"]


class BenchArgument(BaseModel):
    """構造化出力ベンチ用のスキーマ。"""

    stance: Literal["賛成", "反対"]
    claim: str = Field(description="主張の要旨(1文)")
    reasons: list[str] = Field(min_length=2, max_length=4, description="根拠(各1文)")
    confidence: float = Field(ge=0, le=1, description="主張への確信度")


class BenchRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    model_key: str
    model: str
    roles: list[str]
    task: BenchTask
    runs: int
    successes: int
    mean_retries: float | None
    median_ttft_ms: float | None
    median_total_ms: float | None
    mean_tokens_per_s: float | None
    modes: dict[str, int]
    errors: list[str]

    @property
    def success_rate(self) -> float:
        return self.successes / self.runs if self.runs else 0.0


def _median(values: Sequence[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return statistics.median(present) if present else None


def _mean(values: Sequence[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return statistics.fmean(present) if present else None


def summarize(
    model_key: str, model: str, roles: list[str], task: BenchTask, records: list[LLMCallRecord]
) -> BenchRow:
    ok = [r for r in records if r.success]
    return BenchRow(
        model_key=model_key,
        model=model,
        roles=roles,
        task=task,
        runs=len(records),
        successes=len(ok),
        mean_retries=_mean([float(r.retries) for r in records]) if task == "structured" else None,
        median_ttft_ms=_median([r.ttft_ms for r in ok]),
        median_total_ms=_median([r.total_ms for r in ok]),
        mean_tokens_per_s=_mean([r.tokens_per_s for r in ok]),
        modes=dict(Counter(r.structured_mode for r in records if r.structured_mode)),
        errors=[r.error for r in records if r.error],
    )


async def run_bench(
    client: LLMClient,
    recorder: InMemoryRecorder,
    prompts: PromptLoader,
    roles: Sequence[Role],
    n: int,
    *,
    on_progress: Callable[[str], None] | None = None,
) -> list[BenchRow]:
    """役割のモデルごとに自由生成と構造化出力を n 回ずつ順に実行する。

    `recorder` は `client` に渡したもの。成功・失敗とも 1 呼び出し 1 件の記録を集計する。
    同じモデルに割り当てられた役割はまとめて 1 回だけ計測する。接続できない場合は
    `LLMConnectionError` をそのまま送出する。
    """
    by_model: dict[str, list[Role]] = {}
    for role in roles:
        by_model.setdefault(client.config.roles[role], []).append(role)

    rows: list[BenchRow] = []
    for model_key, model_roles in by_model.items():
        role = model_roles[0]
        model = client.config.models[model_key].model
        role_names = [r.value for r in model_roles]
        for task in ("text", "structured"):
            records: list[LLMCallRecord] = []
            for i in range(n):
                topic, stance = BENCH_TOPICS[i % len(BENCH_TOPICS)]
                if on_progress:
                    on_progress(f"{model} / {task} {i + 1}/{n}")
                before = len(recorder.records)
                try:
                    if task == "text":
                        prompt = prompts.render("bench/free", topic=topic, stance=stance)
                        await client.generate_text(role, prompt)
                    else:
                        prompt = prompts.render("bench/structured", topic=topic, stance=stance)
                        await client.generate_structured(role, prompt, BenchArgument)
                except LLMConnectionError:
                    raise
                except LLMError:
                    pass  # 失敗もクライアントが記録済みで、集計に含める
                records.extend(recorder.records[before:])
            rows.append(summarize(model_key, model, role_names, task, records))
    return rows
