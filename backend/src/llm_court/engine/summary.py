"""イベント(状態)から計測サマリを作る。"""

from collections import Counter
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict

from llm_court.domain import DebatePhase, Event, Side
from llm_court.engine.state import DebateState


class TurnMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    statement_id: str
    side: Side
    phase: DebatePhase
    round: int
    chars: int
    ttft_ms: float | None
    total_ms: float | None
    output_tokens: int | None
    tokens_per_s: float | None


class DebateSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    turns: list[TurnMetrics]
    llm_calls: int
    input_tokens: int
    output_tokens: int
    llm_time_ms: float
    """全 LLM 呼び出しの時間の合計(並列実行分も足す)。"""
    structured_calls: int
    structured_failures: int
    structured_retries: int
    citation_issues: dict[str, int]
    claims: int
    wall_time_s: float | None
    """開廷から最後のイベントまでの実時間(捜査を含む)。"""


def summarize(events: Sequence[Event]) -> DebateSummary:
    state = DebateState.from_events(events)
    calls = {c.call_id: c for c in state.llm_calls}
    turns: list[TurnMetrics] = []
    for s in state.statements:
        call = calls.get(state.statement_calls.get(s.id, ""))
        turns.append(
            TurnMetrics(
                statement_id=s.id,
                side=s.side,
                phase=s.phase,
                round=s.round,
                chars=len(s.text),
                ttft_ms=call.ttft_ms if call else None,
                total_ms=call.total_ms if call else None,
                output_tokens=call.output_tokens if call else None,
                tokens_per_s=call.tokens_per_s if call else None,
            )
        )
    structured = [c for c in state.llm_calls if c.kind == "structured"]
    wall_time_s = (events[-1].timestamp - events[0].timestamp).total_seconds() if events else None
    return DebateSummary(
        turns=turns,
        llm_calls=len(state.llm_calls),
        input_tokens=sum(c.input_tokens or 0 for c in state.llm_calls),
        output_tokens=sum(c.output_tokens or 0 for c in state.llm_calls),
        llm_time_ms=sum(c.total_ms for c in state.llm_calls),
        structured_calls=len(structured),
        structured_failures=sum(not c.success for c in structured),
        structured_retries=sum(c.retries for c in structured),
        citation_issues=dict(Counter(i.kind for i in state.citation_issues)),
        claims=len(state.claims),
        wall_time_s=wall_time_s,
    )
