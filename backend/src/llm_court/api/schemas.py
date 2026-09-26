"""API のリクエスト・レスポンスのモデル。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from llm_court.api.tasks import TaskView
from llm_court.domain import (
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


class NextTurn(BaseModel):
    """次に進む手番。"""

    model_config = ConfigDict(frozen=True)

    kind: Literal["statement", "verdict"]
    phase: DebatePhase
    round: int
    side: Side | None = None


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
        next_turn = NextTurn(kind="statement", phase=step.phase, round=step.round, side=step.side)
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
    )
