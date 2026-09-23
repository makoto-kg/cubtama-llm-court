"""追記専用のイベントログのイベント定義。

ゲーム状態の真実はこのイベント列。状態は `engine.state.DebateState.from_events` で再構築する。
"""

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from llm_court.domain.debate import (
    CitationIssue,
    Claim,
    DebatePhase,
    JudgeScore,
    Statement,
    Verdict,
)
from llm_court.domain.evidence import ResearchReport


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
    | LLMCallRecorded,
    Field(discriminator="type"),
]

EVENT_ADAPTER: TypeAdapter[Event] = TypeAdapter(Event)
