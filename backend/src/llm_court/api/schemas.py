"""API のリクエスト・レスポンスのモデル。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from llm_court.api.redaction import redact_choices
from llm_court.api.tasks import TaskView
from llm_court.domain import (
    ChoiceOption,
    CitationIssue,
    Claim,
    DebatePhase,
    Evidence,
    JudgeScore,
    Side,
    Statement,
    Verdict,
)
from llm_court.engine.debate import next_step
from llm_court.engine.state import DebateState
from llm_court.modes import DebateMode

SessionStatus = Literal["awaiting_evidence", "ready", "in_progress", "finished", "aborted"]


class CreateSessionRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=200, description="論題")
    rounds: int = Field(default=3, ge=1, le=10, description="反論の往復数")
    human_side: Side | None = Field(
        default=None, description="人間が担当する陣営。省略すると LLM vs LLM"
    )


class ChooseRequest(BaseModel):
    option_id: str = Field(min_length=1, description="選ぶ選択肢の ID")


class ChoicesView(BaseModel):
    """人間の手番で示されている選択肢(強さは伏せてある)。"""

    model_config = ConfigDict(frozen=True)

    session_id: str
    phase: DebatePhase
    round: int
    side: Side
    options: list[ChoiceOption]
    penalty_gauge: int


class NextTurn(BaseModel):
    """次に進む手番。"""

    model_config = ConfigDict(frozen=True)

    kind: Literal["statement", "verdict"]
    phase: DebatePhase
    round: int
    side: Side | None = None
    by_human: bool = False
    """人間の手番(選択肢から選ぶ)か。"""


class SessionListItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: str
    topic: str
    status: SessionStatus
    created_at: datetime


class SessionView(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: str
    topic: str
    rounds: int
    status: SessionStatus
    phase: DebatePhase | None
    round: int
    next_turn: NextTurn | None
    running_task: TaskView | None
    models: dict[str, str]
    evidence: list[Evidence]
    statements: list[Statement]
    claims: list[Claim]
    citation_issues: list[CitationIssue]
    judge_scores: list[JudgeScore]
    verdict: Verdict | None
    aborted: str | None
    human_side: Side | None
    penalty_gauge: int
    penalty_gauge_max: int
    """ゲージの初期値(表示用)。"""
    pending_choices: ChoicesView | None
    """人間の選択待ちの選択肢(強さは伏せてある)。"""
    choices: list[ChoiceOption]
    """人間が選んだ選択肢の履歴(強さを公開)。"""


class TaskAccepted(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: str
    task: TaskView


class ErrorResponse(BaseModel):
    detail: str


def session_status(state: DebateState) -> SessionStatus:
    if state.aborted is not None:
        return "aborted"
    if state.verdict is not None:
        return "finished"
    if state.research is None:
        return "awaiting_evidence"
    return "in_progress" if state.statements else "ready"


def session_view(state: DebateState, mode: DebateMode, task: TaskView | None) -> SessionView:
    assert state.session_id is not None and state.topic is not None
    step = next_step(state, mode)
    next_turn: NextTurn | None = None
    if step == "verdict":
        next_turn = NextTurn(kind="verdict", phase=DebatePhase.VERDICT, round=0)
    elif step is not None:
        next_turn = NextTurn(
            kind="statement",
            phase=step.phase,
            round=step.round,
            side=step.side,
            by_human=step.side is state.human_side,
        )
    return SessionView(
        session_id=state.session_id,
        topic=state.topic,
        rounds=state.rounds,
        status=session_status(state),
        phase=state.phase,
        round=state.round,
        next_turn=next_turn,
        running_task=task,
        models=state.models,
        evidence=state.evidence,
        statements=state.statements,
        claims=state.claims,
        citation_issues=state.citation_issues,
        judge_scores=state.judge_scores,
        verdict=state.verdict,
        aborted=state.aborted,
        human_side=state.human_side,
        penalty_gauge=state.penalty_gauge,
        penalty_gauge_max=state.penalty_gauge_max,
        pending_choices=choices_view(state),
        choices=[c.option for c in state.choices],
    )


def choices_view(state: DebateState) -> ChoicesView | None:
    pending = state.pending_choices
    if pending is None or state.session_id is None:
        return None
    redacted = redact_choices(pending)
    return ChoicesView(
        session_id=state.session_id,
        phase=redacted.phase,
        round=redacted.round,
        side=redacted.side,
        options=redacted.options,
        penalty_gauge=state.penalty_gauge,
    )


class EvidenceSample(BaseModel):
    """同梱の捜査結果(ブラウザから証拠品として選べる)。"""

    model_config = ConfigDict(frozen=True)

    name: str
    topic: str
    evidence_count: int
    created_at: datetime


class RoleAssignment(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: str
    model_key: str
    model: str
    reasoning: str | None
    provider: str
    base_url: str
    json_schema: bool
    json_mode: bool
    streaming: bool
    max_concurrency: int


class ConfigView(BaseModel):
    """役割ごとのモデル割り当て(設定画面用。api_key は含めない)。"""

    model_config = ConfigDict(frozen=True)

    roles: list[RoleAssignment]
