from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime

import pytest

from llm_court.domain import (
    DebatePhase,
    Event,
    ResearchReport,
    SessionAborted,
    Side,
    StatementMade,
)
from llm_court.engine.debate import (
    DebateEngine,
    DebateError,
    DebateObserver,
    ResearchFn,
    SessionNotFoundError,
    SessionStateError,
    next_step,
)
from llm_court.engine.record import render_markdown
from llm_court.engine.recorder import BufferedRecorder
from llm_court.engine.state import DebateState, InvalidEventError
from llm_court.engine.store import EventStore
from llm_court.engine.summary import summarize
from llm_court.llm import LLMClient, LLMConnectionError, PromptLoader
from llm_court.modes import DEBATE_MODE, Turn
from tests.debate_fakes import AFFIRMATIVE_TEXT, DebateResponder
from tests.fakes import FakeChatBackend, FakeError, FakeResponse
from tests.unit.test_llm_client import make_config


class RecordingObserver(DebateObserver):
    def __init__(self) -> None:
        self.events: list[Event] = []
        self.tokens: list[tuple[Side, str]] = []
        self.starts: list[Turn] = []
        self.progress: list[str] = []

    def on_event(self, event: Event) -> None:
        self.events.append(event)

    def on_progress(self, message: str) -> None:
        self.progress.append(message)

    def on_statement_start(self, turn: Turn) -> None:
        self.starts.append(turn)

    def on_token(self, turn: Turn, chunk: str) -> None:
        self.tokens.append((turn.side, chunk))


@pytest.fixture
async def store() -> AsyncIterator[EventStore]:
    s = await EventStore.open(None)
    yield s
    await s.aclose()


def make_engine(
    prompts: PromptLoader,
    store: EventStore,
    fake: FakeChatBackend,
    *,
    research: ResearchFn | None = None,
    observer: DebateObserver | None = None,
    max_retries: int = 1,
) -> DebateEngine:
    recorder = BufferedRecorder()
    llm = LLMClient(
        make_config(),
        prompts=prompts,
        structured_max_retries=max_retries,
        backend_factory=lambda _p: fake,
        recorder=recorder,
    )
    return DebateEngine(
        llm=llm,
        recorder=recorder,
        prompts=prompts,
        store=store,
        mode=DEBATE_MODE,
        research=research,
        observer=observer,
    )


async def test_full_debate(
    prompts: PromptLoader, store: EventStore, research_report: ResearchReport
) -> None:
    observer = RecordingObserver()
    fake = FakeChatBackend(responder=DebateResponder())
    engine = make_engine(prompts, store, fake, observer=observer)
    state = await engine.run(research_report.topic, 1, evidence=research_report)

    # 進行: 冒頭陳述 → 反論 1 → 最終弁論 → 判決
    phases = [(e.phase, e.round) for e in observer.events if e.type == "phase_started"]
    assert phases == [
        (DebatePhase.OPENING, 0),
        (DebatePhase.REBUTTAL, 1),
        (DebatePhase.CLOSING, 0),
        (DebatePhase.VERDICT, 0),
    ]
    assert [s.side for s in state.statements] == [Side.AFFIRMATIVE, Side.NEGATIVE] * 3
    assert [s.id for s in state.statements][:2] == ["S-01", "S-02"]
    assert state.statements[0].text == AFFIRMATIVE_TEXT
    assert state.statements[1].cited_evidence_ids == ["EV-02", "EV-09"]

    # 否定側の架空の証拠品は毎回検出される
    assert [i.kind for i in state.citation_issues] == ["unknown_evidence"] * 3
    assert {i.statement_id for i in state.citation_issues} == {"S-02", "S-04", "S-06"}

    # 主張: ID の正規化と未知 ID の除去
    assert len(state.claims) == 12
    assert state.claims[0].id == "C-01"
    assert state.claims[0].cited_evidence_ids == ["EV-01"]
    assert state.claims[1].cited_evidence_ids == []

    # 判決: 提示順を入れ替えた 2 回の評価
    assert [s.order for s in state.judge_scores] == [
        [Side.AFFIRMATIVE, Side.NEGATIVE],
        [Side.NEGATIVE, Side.AFFIRMATIVE],
    ]
    assert state.verdict is not None
    assert state.verdict.winner is Side.AFFIRMATIVE
    assert state.verdict.agreed

    # 計測: 発言 6 + 主張抽出 6 + 裁判長 2
    assert len(state.llm_calls) == 14
    assert all(state.statement_calls[s.id] for s in state.statements)

    # 表示用のコールバック
    assert len(observer.starts) == 6
    assert observer.tokens[0] == (Side.AFFIRMATIVE, AFFIRMATIVE_TEXT)

    # 状態はストアのイベントから再構築したものと一致する
    events = await store.load(engine.session_id)
    assert DebateState.from_events(events) == state
    assert [e.seq for e in events] == list(range(1, len(events) + 1))
    statement_event = next(e for e in events if isinstance(e, StatementMade))
    assert statement_event.role == "debater"
    assert statement_event.prompt_version is not None


async def test_debater_context(
    prompts: PromptLoader, store: EventStore, research_report: ResearchReport
) -> None:
    fake = FakeChatBackend(responder=DebateResponder())
    await make_engine(prompts, store, fake).run(research_report.topic, 1, evidence=research_report)
    debater_requests = [r for r in fake.requests if r.response_format is None]
    first, second = (
        debater_requests[0].messages[-1].content,
        debater_requests[1].messages[-1].content,
    )
    assert "[EV-01] フィンランドの給付実験" in first
    assert "未検証の事実" not in first  # 未検証の事実は渡さない
    assert "(まだありません)" in first
    # 2 番目の論者には相手の直前の発言と主張ログが渡る
    assert AFFIRMATIVE_TEXT in second
    assert "雇用への影響は小さい" in second


async def test_judge_disagreement_is_draw(
    prompts: PromptLoader, store: EventStore, research_report: ResearchReport
) -> None:
    fake = FakeChatBackend(responder=DebateResponder(judge_scores=[(8, 6), (5, 7)]))
    state = await make_engine(prompts, store, fake).run("論題", 1, evidence=research_report)
    assert state.verdict is not None
    assert state.verdict.winner is None
    assert not state.verdict.agreed


async def test_claim_extraction_failure_does_not_stop(
    prompts: PromptLoader, store: EventStore, research_report: ResearchReport
) -> None:
    fake = FakeChatBackend(responder=DebateResponder(claims_json="JSON ではない"))
    state = await make_engine(prompts, store, fake, max_retries=0).run(
        "論題", 1, evidence=research_report
    )
    assert state.verdict is not None
    assert state.claims == []
    summary = summarize(await store.load(state.session_id or ""))
    assert summary.structured_failures == 6
    assert summary.structured_calls == 8


async def test_research_is_used_when_no_evidence(
    prompts: PromptLoader, store: EventStore, research_report: ResearchReport
) -> None:
    calls: list[str] = []

    async def research(topic: str, progress: Callable[[str], None]) -> ResearchReport:
        calls.append(topic)
        return research_report

    fake = FakeChatBackend(responder=DebateResponder())
    state = await make_engine(prompts, store, fake, research=research).run("論題", 1)
    assert calls == ["論題"]
    assert state.research == research_report


async def test_abort_is_recorded(
    prompts: PromptLoader, store: EventStore, research_report: ResearchReport
) -> None:
    fake = FakeChatBackend(
        responder=lambda _r: FakeResponse(error=FakeError(kind="connection", message="down"))
    )
    engine = make_engine(prompts, store, fake)
    with pytest.raises(LLMConnectionError):
        await engine.run("論題", 1, evidence=research_report)
    events = await store.load(engine.session_id)
    assert isinstance(events[-1], SessionAborted)
    state = DebateState.from_events(events)
    assert state.aborted is not None
    assert state.llm_calls and not state.llm_calls[0].success


async def test_empty_statement_aborts(
    prompts: PromptLoader, store: EventStore, research_report: ResearchReport
) -> None:
    fake = FakeChatBackend(responder=lambda _r: FakeResponse.text("<think>考えただけ</think>"))
    engine = make_engine(prompts, store, fake)
    with pytest.raises(DebateError, match="空"):
        await engine.run("論題", 1, evidence=research_report)


async def test_no_evidence_aborts(
    prompts: PromptLoader, store: EventStore, research_report: ResearchReport
) -> None:
    empty = research_report.model_copy(update={"evidence": []})
    engine = make_engine(prompts, store, FakeChatBackend(responder=DebateResponder()))
    with pytest.raises(DebateError, match="証拠品"):
        await engine.run("論題", 1, evidence=empty)


async def test_state_rejects_out_of_order_events(
    prompts: PromptLoader, store: EventStore, research_report: ResearchReport
) -> None:
    fake = FakeChatBackend(responder=DebateResponder())
    engine = make_engine(prompts, store, fake)
    await engine.run("論題", 1, evidence=research_report)
    events = await store.load(engine.session_id)

    with pytest.raises(InvalidEventError, match="開廷前"):
        DebateState.from_events(events[1:])
    with pytest.raises(InvalidEventError, match="単調増加"):
        DebateState.from_events([events[0], events[0]])
    statement = next(e for e in events if isinstance(e, StatementMade))
    with pytest.raises(InvalidEventError, match="フェーズ"):
        DebateState.from_events([events[0], statement])
    late = statement.model_copy(update={"seq": 10_000, "timestamp": datetime.now(UTC)})
    with pytest.raises(InvalidEventError, match="閉廷後"):
        DebateState.from_events([*events, late])


async def test_markdown_and_summary(
    prompts: PromptLoader, store: EventStore, research_report: ResearchReport
) -> None:
    fake = FakeChatBackend(responder=DebateResponder())
    engine = make_engine(prompts, store, fake)
    state = await engine.run(research_report.topic, 1, evidence=research_report)
    md = render_markdown(state, DEBATE_MODE)
    assert md.startswith("# 法廷記録: ベーシックインカムを導入すべきか")
    assert "### EV-01 フィンランドの給付実験(2020-06-25)" in md
    assert "### 反論 第1回" in md
    assert "⚠ 存在しない証拠品: EV-09 は存在しない証拠品です" in md
    assert "| 1 | 肯定側 → 否定側 | 肯定側 | 8 | 8 | 8 | 8 | 32 |" in md
    assert "**肯定側の勝ち**" in md

    summary = summarize(await store.load(engine.session_id))
    assert [t.statement_id for t in summary.turns] == [f"S-0{i}" for i in range(1, 7)]
    assert all(t.total_ms is not None for t in summary.turns)
    assert summary.citation_issues == {"unknown_evidence": 3}
    assert summary.llm_calls == 14
    assert summary.claims == 12
    assert summary.wall_time_s is not None


# --- 1 ステップずつの進行と再開 ---


async def test_step_by_step_and_resume(
    prompts: PromptLoader, store: EventStore, research_report: ResearchReport
) -> None:
    fake = FakeChatBackend(responder=DebateResponder())
    engine = make_engine(prompts, store, fake)
    session_id = await engine.start("論題", 1)
    assert next_step(engine.state, DEBATE_MODE) is None  # 証拠品がまだない
    with pytest.raises(SessionStateError, match="証拠品"):
        await engine.advance()

    await engine.collect_evidence(research_report)
    with pytest.raises(SessionStateError, match="すでに"):
        await engine.collect_evidence(research_report)

    step = await engine.advance()
    assert isinstance(step, Turn)
    assert (step.phase, step.side) == (DebatePhase.OPENING, Side.AFFIRMATIVE)
    assert len(engine.state.statements) == 1

    # 別のエンジン(再起動相当)でストアから再開する
    resumed = make_engine(prompts, store, fake)
    state = await resumed.resume(session_id)
    assert state == engine.state
    step = await resumed.advance()
    assert isinstance(step, Turn) and step.side is Side.NEGATIVE

    # 反論に入るときは PhaseStarted が 1 回だけ出る
    await resumed.advance()
    phases = [e for e in await store.load(session_id) if e.type == "phase_started"]
    assert [(e.phase, e.round) for e in phases] == [
        (DebatePhase.OPENING, 0),
        (DebatePhase.REBUTTAL, 1),
    ]

    final = await resumed.run_to_end()
    assert final.verdict is not None
    assert next_step(final, DEBATE_MODE) is None
    with pytest.raises(SessionStateError, match="手番"):
        await resumed.advance()
    assert DebateState.from_events(await store.load(session_id)) == final


async def test_resume_unknown_session(prompts: PromptLoader, store: EventStore) -> None:
    engine = make_engine(prompts, store, FakeChatBackend())
    with pytest.raises(SessionNotFoundError):
        await engine.resume("nope")


async def test_state_error_does_not_abort(
    prompts: PromptLoader, store: EventStore, research_report: ResearchReport
) -> None:
    engine = make_engine(prompts, store, FakeChatBackend(responder=DebateResponder()))
    await engine.start("論題", 1)
    with pytest.raises(SessionStateError):
        await engine.advance()
    assert engine.state.aborted is None


async def test_recorder_isolated_per_task() -> None:
    import asyncio

    from llm_court.llm import LLMCallRecord

    recorder = BufferedRecorder()

    def record(role: str) -> None:
        recorder.record(
            LLMCallRecord(
                started_at=datetime.now(UTC),
                role=role,
                model_key="m",
                model="m",
                provider="p",
                kind="text",
                total_ms=1,
                success=True,
            )
        )

    async def task(role: str) -> list[str]:
        with recorder.isolated():
            record(role)
            await asyncio.sleep(0)
            # 子タスクの記録も同じバッファに入る
            await asyncio.gather(asyncio.to_thread(lambda: None), _child(record, role))
            return [c.role for c in recorder.drain()]

    a, b = await asyncio.gather(task("a"), task("b"))
    assert a == ["a", "a"]
    assert b == ["b", "b"]
    record("shared")
    assert [c.role for c in recorder.drain()] == ["shared"]


async def _child(record: Callable[[str], None], role: str) -> None:
    record(role)
