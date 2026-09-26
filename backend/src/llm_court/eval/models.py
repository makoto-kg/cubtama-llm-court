"""評価の実行結果のモデル。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from llm_court.domain import Event, JudgeScore, LLMCallInfo, Verdict
from llm_court.eval.analyst_eval import CandidateSetEval

JudgingSource = Literal["debate", "repeat", "reference"]


class Judging(BaseModel):
    """1 回の判定(2 つの提示順の評価の組と、そこから決めた判決)。"""

    model_config = ConfigDict(frozen=True)

    source: JudgingSource
    """debate: ディベート中の判決、repeat: 同じ裁判長による再評価、reference: 参照用裁判長。"""
    repeat: int = 0
    scores: list[JudgeScore]
    verdict: Verdict


class DebateRun(BaseModel):
    model_config = ConfigDict(frozen=True)

    config: str
    topic: str
    run: int
    session_id: str
    events: list[Event] = []
    """ディベートのイベント列(result.json には含めず、debates/*.jsonl に保存する)。"""
    judgings: list[Judging]
    judge_calls: list[LLMCallInfo]
    """再評価・参照評価・分析官評価の LLM 呼び出し(ディベートのイベントには含まれない)。"""
    analyst: list[CandidateSetEval] = []
    """分析官の候補精度の評価(仕様で有効にしたときのみ)。"""
    error: str | None = None


class EvalResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    started_at: datetime
    finished_at: datetime
    rounds: int
    judge_repeats: int
    configs: dict[str, dict[str, str]]
    """構成名 → 役割 → モデル ID。"""
    reference_judge: str | None
    runs: list[DebateRun]
