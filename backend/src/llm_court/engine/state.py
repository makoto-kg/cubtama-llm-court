"""イベント列からのディベート状態の再構築。"""

from collections.abc import Iterable
from typing import Self

from pydantic import BaseModel, ConfigDict

from llm_court.domain import (
    CitationIssue,
    CitationIssuesDetected,
    Claim,
    ClaimsExtracted,
    DebatePhase,
    Event,
    Evidence,
    EvidenceCollected,
    JudgeScore,
    JudgeScored,
    LLMCallInfo,
    LLMCallRecorded,
    PhaseStarted,
    ResearchReport,
    SessionAborted,
    SessionStarted,
    Statement,
    StatementMade,
    Verdict,
    VerdictDelivered,
)


class InvalidEventError(Exception):
    """現在の状態に適用できないイベント。"""


class DebateState(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: str | None = None
    topic: str | None = None
    rounds: int = 0
    models: dict[str, str] = {}
    research: ResearchReport | None = None
    phase: DebatePhase | None = None
    round: int = 0
    statements: list[Statement] = []
    statement_calls: dict[str, str] = {}
    """発言 ID → 生成した LLM 呼び出しの call_id。"""
    claims: list[Claim] = []
    citation_issues: list[CitationIssue] = []
    judge_scores: list[JudgeScore] = []
    verdict: Verdict | None = None
    aborted: str | None = None
    llm_calls: list[LLMCallInfo] = []
    last_seq: int = 0

    @classmethod
    def from_events(cls, events: Iterable[Event]) -> Self:
        state = cls()
        for event in events:
            state = state.apply(event)
        return state

    @property
    def evidence(self) -> list[Evidence]:
        return self.research.evidence if self.research else []

    @property
    def evidence_by_id(self) -> dict[str, Evidence]:
        return {e.id: e for e in self.evidence}

    @property
    def finished(self) -> bool:
        return self.verdict is not None or self.aborted is not None

    def statement(self, statement_id: str) -> Statement:
        for s in self.statements:
            if s.id == statement_id:
                return s
        raise KeyError(statement_id)

    def apply(self, event: Event) -> Self:
        """イベントを 1 件適用した新しい状態を返す(元の状態は変えない)。"""
        if event.seq and event.seq <= self.last_seq:
            raise InvalidEventError(f"seq が単調増加していません: {event.seq}")
        if not isinstance(event, SessionStarted) and self.session_id is None:
            raise InvalidEventError(f"開廷前のイベントです: {event.type}")
        if self.finished and not isinstance(event, LLMCallRecorded):
            raise InvalidEventError(f"閉廷後のイベントです: {event.type}")

        update: dict[str, object] = {"last_seq": event.seq or self.last_seq}
        match event:
            case SessionStarted():
                if self.session_id is not None:
                    raise InvalidEventError("すでに開廷しています")
                update |= {
                    "session_id": event.session_id,
                    "topic": event.topic,
                    "rounds": event.rounds,
                    "models": event.models,
                }
            case EvidenceCollected():
                update["research"] = event.report
            case PhaseStarted():
                update |= {"phase": event.phase, "round": event.round}
            case StatementMade():
                statement = event.statement
                if self.phase is None or statement.phase != self.phase:
                    raise InvalidEventError(
                        f"フェーズ {self.phase} 中に {statement.phase} の発言はできません"
                    )
                update["statements"] = [*self.statements, statement]
                if event.call_id:
                    update["statement_calls"] = {
                        **self.statement_calls,
                        statement.id: event.call_id,
                    }
            case CitationIssuesDetected():
                self.statement(event.statement_id)
                update["citation_issues"] = [*self.citation_issues, *event.issues]
            case ClaimsExtracted():
                self.statement(event.statement_id)
                update["claims"] = [*self.claims, *event.claims]
            case JudgeScored():
                if self.phase is not DebatePhase.VERDICT:
                    raise InvalidEventError("判決フェーズ以外で採点はできません")
                update["judge_scores"] = [*self.judge_scores, event.score]
            case VerdictDelivered():
                if self.phase is not DebatePhase.VERDICT:
                    raise InvalidEventError("判決フェーズ以外で判決は出せません")
                update["verdict"] = event.verdict
            case SessionAborted():
                update["aborted"] = event.reason
            case LLMCallRecorded():
                update["llm_calls"] = [*self.llm_calls, event.call]
        return self.model_copy(update=update)
