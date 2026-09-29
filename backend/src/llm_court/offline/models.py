"""オフラインパック: フロントエンドだけで裁判を遊ぶための静的データ(事件 1 件 = 1 ファイル)。

進行(選択肢・正誤・減点・解説)に必要な情報と、起こりうる全行動に対する証人の応答を
事前に生成して含める。正解もブラウザに届くが、クライアントだけのゲームとして許容する(ADR 0014)。
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from llm_court.domain import CasePublic, DeviationCheck, Explanation, LLMCallInfo


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class OfflineTrap(_Frozen):
    evidence_id: str
    why_tempting: str


class OfflineContradiction(_Frozen):
    id: str
    testimony_line_id: str
    evidence_id: str
    traps: list[OfflineTrap]


class OfflineAnswers(_Frozen):
    """進行に必要な非公開の情報(真相・台本は含めない)。"""

    contradictions: list[OfflineContradiction]
    answer_index: int


class OfflineMode(_Frozen):
    penalty_gauge: int
    penalties: dict[str, int]
    distractor_options: int
    probe_options: int


class OfflineResponse(_Frozen):
    """1 つの行動に対する証人の応答。"""

    key: str
    """行動キー(`present:<行>:<証拠品>` / `probe:<行>`)。"""
    witness_id: str
    text: str
    should_collapse: bool
    check: DeviationCheck | None
    attempts: int
    """作り直しを含む生成の回数。"""
    call: LLMCallInfo | None = None
    """採用した応答の LLM 呼び出しの記録(閉廷後の思考ログ用)。"""


class OfflineMeta(_Frozen):
    generated_at: datetime
    models: dict[str, str]
    prompt_versions: dict[str, str]
    responses: int
    deviations: int
    """逸脱が残った応答の数。"""
    unchecked: int
    source: Literal["simulated", "scripted"] = "simulated"
    """応答の出どころ。simulated = LLM で事前生成、scripted = 人が書いた台本(ADR 0016)。"""
    tutorial: bool = False


class OfflinePack(_Frozen):
    format_version: int = 1
    case: CasePublic
    theme: str
    answers: OfflineAnswers
    explanation: Explanation
    mode: OfflineMode
    responses: list[OfflineResponse]
    meta: OfflineMeta


class OfflineIndexItem(_Frozen):
    id: str
    title: str
    theme: str
    overview: str
    testimonies: int
    contradictions: int
    responses: int
    generated_at: datetime
    tutorial: bool = False


class OfflineIndex(_Frozen):
    """オフラインで遊べる事件の一覧(`index.json`)。"""

    cases: list[OfflineIndexItem]


def present_key(line_id: str, evidence_id: str) -> str:
    return f"present:{line_id}:{evidence_id}"


def probe_key(line_id: str) -> str:
    return f"probe:{line_id}"
