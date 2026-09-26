from collections.abc import AsyncIterator

import pytest

from llm_court.domain import (
    ChoiceMade,
    ChoicesPrepared,
    DebatePhase,
    PenaltyApplied,
    ResearchReport,
    Side,
    StatementMade,
)
from llm_court.engine.debate import (
    DebateEngine,
    InvalidChoiceError,
    SessionStateError,
)
from llm_court.engine.recorder import BufferedRecorder
from llm_court.engine.state import DebateState, InvalidEventError
from llm_court.engine.store import EventStore
from llm_court.llm import LLMClient, PromptLoader
from llm_court.modes import DEBATE_MODE, DebateMode
from tests.debate_fakes import ADVOCATE_TEXT, DebateResponder, contradictions_json
from tests.fakes import FakeChatBackend
from tests.unit.test_llm_client import make_config


@pytest.fixture
async def store() -> AsyncIterator[EventStore]:
    s = await EventStore.open(None)
    yield s
    await s.aclose()


def make_engine(
    prompts: PromptLoader,
    store: EventStore,
    responder: DebateResponder | None = None,
    *,
    mode: DebateMode = DEBATE_MODE,
    max_retries: int = 1,
) -> tuple[DebateEngine, FakeChatBackend]:
    fake = FakeChatBackend(responder=responder or DebateResponder())
    recorder = BufferedRecorder()
    llm = LLMClient(
        make_config(),
        prompts=prompts,
        structured_max_retries=max_retries,
        backend_factory=lambda _p: fake,
        recorder=recorder,
    )
    engine = DebateEngine(llm=llm, recorder=recorder, prompts=prompts, store=store, mode=mode)
    return engine, fake


async def start_game(
    engine: DebateEngine, report: ResearchReport, human: Side, rounds: int = 1
) -> str:
    session_id = await engine.start("論題", rounds, human_side=human)
    await engine.collect_evidence(report)
    await engine.run_to_end()
    return session_id


def pending(engine: DebateEngine) -> ChoicesPrepared:
    choices = engine.state.pending_choices
    assert choices is not None
    return choices


async def test_human_negative_full_game(
    prompts: PromptLoader, store: EventStore, research_report: ResearchReport
) -> None:
    engine, _ = make_engine(prompts, store)
    session_id = await start_game(engine, research_report, Side.NEGATIVE)
    state = engine.state
    assert state.human_side is Side.NEGATIVE
    assert state.penalty_gauge == DEBATE_MODE.penalty_gauge
    assert state.models["analyst"] and state.models["advocate"]

    # 肯定側(LLM)の冒頭陳述の後、否定側の冒頭陳述の選択待ちで止まる(先行実行)
    assert [s.side for s in state.statements] == [Side.AFFIRMATIVE]
    opening = pending(engine)
    assert (opening.phase, opening.side) == (DebatePhase.OPENING, Side.NEGATIVE)
    assert [o.kind for o in opening.options] == ["argument", "argument"]
    assert opening.discarded == 1  # 存在しない証拠品だけの方針は捨てる
    assert opening.options[1].evidence_ids == ["EV-02"]
    assert opening.options[0].id == "T02-1"

    with pytest.raises(SessionStateError, match="選択待ち"):
        await engine.advance()
    with pytest.raises(InvalidChoiceError):
        await engine.choose("nope")

    await engine.choose(opening.options[0].id)
    human_statement = engine.state.statements[-1]
    assert (human_statement.side, human_statement.text) == (Side.NEGATIVE, ADVOCATE_TEXT)
    assert engine.state.penalty_gauge == DEBATE_MODE.penalty_gauge  # 方針の選択は減点なし

    # 肯定側の反論 → 否定側の反論の選択肢(矛盾候補 3 + ゆさぶる 1)
    await engine.run_to_end()
    rebuttal = pending(engine)
    assert rebuttal.phase is DebatePhase.REBUTTAL
    kinds = [o.kind for o in rebuttal.options]
    assert kinds == ["contradiction"] * 3 + ["probe"]
    assert rebuttal.discarded == 1  # 存在しない主張 ID の候補
    strengths = {o.strength for o in rebuttal.options if o.kind == "contradiction"}
    assert strengths == {"strong", "weak", "trap"}
    target = rebuttal.options[0].contradiction
    assert target is not None
    assert target.target_claim_id in {c.id for c in engine.state.claims}
    evidence_option = next(
        o for o in rebuttal.options if o.contradiction and o.contradiction.evidence_id
    )
    assert evidence_option.contradiction is not None
    assert evidence_option.contradiction.evidence_id == "EV-01"  # 表記ゆれを正規化
    assert "EV-01「フィンランドの給付実験」をつきつける(証拠との矛盾)" in evidence_option.label

    weak = next(o for o in rebuttal.options if o.strength == "weak")
    await engine.choose(weak.id)
    assert engine.state.penalty_gauge == DEBATE_MODE.penalty_gauge - 1

    # 最終弁論の方針を選ぶと判決まで進む
    await engine.run_to_end()
    closing = pending(engine)
    assert closing.phase is DebatePhase.CLOSING
    await engine.choose(closing.options[1].id)
    final = await engine.run_to_end()
    assert final.verdict is not None
    assert final.verdict.decided_by == "judge"
    assert len(final.choices) == 3
    assert [s.side for s in final.statements] == [Side.AFFIRMATIVE, Side.NEGATIVE] * 3

    events = await store.load(session_id)
    assert DebateState.from_events(events) == final
    human_events = [e for e in events if isinstance(e, StatementMade) and e.role == "advocate"]
    assert len(human_events) == 3
    penalties = [e for e in events if isinstance(e, PenaltyApplied)]
    assert [(p.amount, p.remaining) for p in penalties] == [(1, 4)]


async def test_penalty_loss(
    prompts: PromptLoader, store: EventStore, research_report: ResearchReport
) -> None:
    mode = DebateMode(penalty_gauge=2)
    engine, _ = make_engine(prompts, store, mode=mode)
    await start_game(engine, research_report, Side.NEGATIVE)
    await engine.choose(pending(engine).options[0].id)
    await engine.run_to_end()
    trap = next(o for o in pending(engine).options if o.strength == "trap")
    statements = len(engine.state.statements)
    await engine.choose(trap.id)

    state = engine.state
    assert state.penalty_gauge == 0
    assert state.verdict is not None
    assert state.verdict.decided_by == "penalty"
    assert state.verdict.winner is Side.AFFIRMATIVE
    assert len(state.statements) == statements  # 清書しない
    assert state.phase is DebatePhase.VERDICT
    with pytest.raises(SessionStateError):
        await engine.advance()


async def test_human_affirmative_starts_with_choices(
    prompts: PromptLoader, store: EventStore, research_report: ResearchReport
) -> None:
    engine, _ = make_engine(prompts, store)
    await start_game(engine, research_report, Side.AFFIRMATIVE)
    assert engine.state.statements == []
    choices = pending(engine)
    assert (choices.phase, choices.side) == (DebatePhase.OPENING, Side.AFFIRMATIVE)
    await engine.choose(choices.options[0].id)
    await engine.run_to_end()
    # 否定側(LLM)は架空の証拠品 EV-09 を引く → 機械検査の候補が strong で加わる
    rebuttal = pending(engine)
    rule = [o for o in rebuttal.options if o.source == "rule"]
    assert len(rule) == 1
    assert rule[0].contradiction is not None
    assert rule[0].contradiction.type == "fabricated_citation"
    assert rule[0].strength == "strong"
    assert "EV-09" in rule[0].pitch


async def test_analyst_falls_back_to_arguments(
    prompts: PromptLoader, store: EventStore, research_report: ResearchReport
) -> None:
    # strong がない出力は検証エラー → 再試行なしで論点の方針に切り替える
    responder = DebateResponder(
        contradictions=lambda targets: contradictions_json(targets, strengths=["weak", "trap"])
    )
    engine, _ = make_engine(prompts, store, responder, max_retries=0)
    await start_game(engine, research_report, Side.NEGATIVE)
    await engine.choose(pending(engine).options[0].id)
    await engine.run_to_end()
    rebuttal = pending(engine)
    assert rebuttal.phase is DebatePhase.REBUTTAL
    assert {o.kind for o in rebuttal.options} == {"argument"}
    failed = [c for c in engine.state.llm_calls if c.schema_name == "ContradictionOutput"]
    assert failed and not failed[-1].success


async def test_choose_outside_human_turn(
    prompts: PromptLoader, store: EventStore, research_report: ResearchReport
) -> None:
    engine, _ = make_engine(prompts, store)
    await engine.start("論題", 1)  # LLM vs LLM
    await engine.collect_evidence(research_report)
    with pytest.raises(SessionStateError, match="手番"):
        await engine.choose("T01-1")


async def test_state_rejects_human_statement_without_choice(
    prompts: PromptLoader, store: EventStore, research_report: ResearchReport
) -> None:
    engine, _ = make_engine(prompts, store)
    session_id = await start_game(engine, research_report, Side.NEGATIVE)
    await engine.choose(pending(engine).options[0].id)
    events = await store.load(session_id)
    # 選択のイベントを抜くと、人間側の発言は不正になる
    without_choice = [e for e in events if not isinstance(e, ChoiceMade)]
    with pytest.raises(InvalidEventError, match="選択"):
        DebateState.from_events(without_choice)
