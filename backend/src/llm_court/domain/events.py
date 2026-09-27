"""追記専用のイベントログのイベント定義。

ゲーム状態の真実はこのイベント列。状態は `engine.state.DebateState.from_events` で再構築する。
"""

from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from llm_court.domain.case import Case
from llm_court.domain.choices import ChoiceOption
from llm_court.domain.debate import (
    CitationIssue,
    Claim,
    DebatePhase,
    JudgeScore,
    Side,
    Statement,
    Verdict,
)
from llm_court.domain.evidence import ResearchReport
from llm_court.domain.trial import DeviationCheck, TrialOption, TrialResult


class LLMCallInfo(BaseModel):
    """LLM 呼び出しの計測記録(`llm.metrics.LLMCallRecord` と同じ形)。

    domain は他のパッケージに依存しないため、同じ形をここで定義する。
    """

    model_config = ConfigDict(frozen=True)

    call_id: str
    started_at: datetime
    role: str
    model_key: str
    model: str
    provider: str
    kind: Literal["text", "structured"]
    prompt_name: str | None = None
    prompt_version: str | None = None
    schema_name: str | None = None
    structured_mode: str | None = None
    ttft_ms: float | None = None
    total_ms: float
    input_tokens: int | None = None
    output_tokens: int | None = None
    tokens_per_s: float | None = None
    success: bool
    attempts: int = 1
    retries: int = 0
    error: str | None = None
    messages: list[dict[str, str]] | None = None
    """最後の試行で送ったメッセージ(role, content)。入出力の記録が無効なら None。"""
    response_text: str | None = None
    """最後の試行の生の出力(本文)。"""
    reasoning_text: str | None = None
    """最後の試行の思考部分(サーバーが分けて返した分。長さに上限あり)。"""
    parsed: dict[str, Any] | None = None
    """構造化出力の検証済みの値。"""


class EventBase(BaseModel):
    """全イベント共通のフィールド。`session_id`・`seq`・`timestamp` はストアが追記時に設定する。"""

    model_config = ConfigDict(frozen=True)

    session_id: str = ""
    seq: int = 0
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    role: str | None = None
    """生成に使った役割。LLM を使わないイベントは None。"""
    model: str | None = None
    prompt_version: str | None = None


class SessionStarted(EventBase):
    type: Literal["session_started"] = "session_started"
    topic: str
    mode: str
    rounds: int
    models: dict[str, str]
    """役割 → モデル ID。"""
    human_side: Side | None = None
    """人間が担当する陣営。None なら LLM vs LLM。"""
    penalty_gauge: int = 0
    """人間側のペナルティゲージの初期値(開始時のモード定義を記録する)。"""


class EvidenceCollected(EventBase):
    type: Literal["evidence_collected"] = "evidence_collected"
    report: ResearchReport


class PhaseStarted(EventBase):
    type: Literal["phase_started"] = "phase_started"
    phase: DebatePhase
    round: int = 0


class StatementMade(EventBase):
    type: Literal["statement_made"] = "statement_made"
    statement: Statement
    call_id: str | None = None
    """発言を生成した LLM 呼び出し(`LLMCallRecorded.call.call_id`)。"""


class CitationIssuesDetected(EventBase):
    type: Literal["citation_issues_detected"] = "citation_issues_detected"
    statement_id: str
    issues: list[CitationIssue]


class ClaimsExtracted(EventBase):
    type: Literal["claims_extracted"] = "claims_extracted"
    statement_id: str
    claims: list[Claim]


class JudgeScored(EventBase):
    type: Literal["judge_scored"] = "judge_scored"
    score: JudgeScore


class VerdictDelivered(EventBase):
    type: Literal["verdict_delivered"] = "verdict_delivered"
    verdict: Verdict


class SessionAborted(EventBase):
    type: Literal["session_aborted"] = "session_aborted"
    reason: str


class ChoicesPrepared(EventBase):
    """人間の手番に示す選択肢(分析官が生成)。"""

    type: Literal["choices_prepared"] = "choices_prepared"
    phase: DebatePhase
    round: int
    side: Side
    options: list[ChoiceOption]
    discarded: int = 0
    """参照が不正で捨てた候補の数。"""


class ChoiceMade(EventBase):
    type: Literal["choice_made"] = "choice_made"
    option: ChoiceOption


class PenaltyApplied(EventBase):
    type: Literal["penalty_applied"] = "penalty_applied"
    amount: int
    remaining: int
    reason: str


# --- 裁判型 ---


class TrialStarted(EventBase):
    """裁判の開廷。事件の全体を含める(状態をログだけで再構築できるように)。"""

    type: Literal["trial_started"] = "trial_started"
    case: Case
    models: dict[str, str]
    penalty_gauge: int


class TestimonyStarted(EventBase):
    type: Literal["testimony_started"] = "testimony_started"
    testimony_id: str


class TrialChoicesPrepared(EventBase):
    type: Literal["trial_choices_prepared"] = "trial_choices_prepared"
    testimony_id: str
    options: list[TrialOption]


class TrialChoiceMade(EventBase):
    type: Literal["trial_choice_made"] = "trial_choice_made"
    option: TrialOption


class WitnessResponded(EventBase):
    type: Literal["witness_responded"] = "witness_responded"
    option_id: str
    witness_id: str
    text: str
    should_collapse: bool
    check: DeviationCheck | None = None
    call_id: str | None = None


class ContradictionSolved(EventBase):
    type: Literal["contradiction_solved"] = "contradiction_solved"
    contradiction_id: str


class AnswerSubmitted(EventBase):
    type: Literal["answer_submitted"] = "answer_submitted"
    index: int
    correct: bool


class TrialFinished(EventBase):
    type: Literal["trial_finished"] = "trial_finished"
    result: TrialResult


class ExplanationObjected(EventBase):
    """「解説に異議あり」。プレイヤーが解説の誤りを報告する。"""

    type: Literal["explanation_objected"] = "explanation_objected"
    target_kind: Literal["learning_point", "contradiction", "trap"]
    target_id: str
    comment: str


class LLMCallRecorded(EventBase):
    type: Literal["llm_call_recorded"] = "llm_call_recorded"
    call: LLMCallInfo


Event = Annotated[
    SessionStarted
    | EvidenceCollected
    | PhaseStarted
    | StatementMade
    | CitationIssuesDetected
    | ClaimsExtracted
    | JudgeScored
    | VerdictDelivered
    | SessionAborted
    | ChoicesPrepared
    | ChoiceMade
    | PenaltyApplied
    | TrialStarted
    | TestimonyStarted
    | TrialChoicesPrepared
    | TrialChoiceMade
    | WitnessResponded
    | ContradictionSolved
    | AnswerSubmitted
    | TrialFinished
    | ExplanationObjected
    | LLMCallRecorded,
    Field(discriminator="type"),
]

EVENT_ADAPTER: TypeAdapter[Event] = TypeAdapter(Event)
