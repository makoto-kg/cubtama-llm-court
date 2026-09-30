from collections.abc import AsyncIterator

import pytest

from llm_court.agents.deviation import deviations_of
from llm_court.agents.trial_analyst import TrialAnalyst
from llm_court.domain import (
    AnswerSubmitted,
    Case,
    ContradictionSolved,
    ResearchReport,
    TrialChoiceMade,
    TrialFinished,
    TrialOption,
)
from llm_court.engine.debate import InvalidChoiceError, SessionStateError
from llm_court.engine.explanation import build_explanation
from llm_court.engine.recorder import BufferedRecorder
from llm_court.engine.state import InvalidEventError
from llm_court.engine.store import EventStore
from llm_court.engine.trial import TrialEngine, TrialError, trap_target_id
from llm_court.engine.trial_state import TrialState
from llm_court.llm import ChatRequest, LLMClient, PromptLoader
from llm_court.modes import TRIAL_MODE, TrialMode
from tests.fakes import FakeChatBackend, FakeResponse
from tests.trial_fakes import COLLAPSE_TEXT, EVADE_TEXT, TrialResponder, make_case, user_text
from tests.unit.test_llm_client import make_config


@pytest.fixture
async def store() -> AsyncIterator[EventStore]:
    s = await EventStore.open(None)
    yield s
    await s.aclose()


@pytest.fixture
async def case(prompts: PromptLoader, research_report: ResearchReport) -> Case:
    return await make_case(prompts, research_report)


def make_engine(
    prompts: PromptLoader,
    store: EventStore,
    responder: TrialResponder | None = None,
    *,
    mode: TrialMode = TRIAL_MODE,
) -> tuple[TrialEngine, TrialResponder]:
    responder = responder or TrialResponder()
    fake = FakeChatBackend(responder=responder)
    recorder = BufferedRecorder()
    llm = LLMClient(
        make_config(),
        prompts=prompts,
        structured_max_retries=0,
        backend_factory=lambda _p: fake,
        recorder=recorder,
    )
    engine = TrialEngine(llm=llm, recorder=recorder, prompts=prompts, store=store, mode=mode)
    return engine, responder


def options(engine: TrialEngine) -> list[TrialOption]:
    pending = engine.state.pending_choices
    assert pending is not None
    return pending.options


def find(engine: TrialEngine, strength: str | None, kind: str = "present") -> TrialOption:
    return next(o for o in options(engine) if o.kind == kind and o.strength == strength)


# --- 分析官 ---


def test_analyst_builds_correct_trap_distractors_and_probes(case: Case) -> None:
    analyst = TrialAnalyst(TRIAL_MODE)
    testimony = case.testimonies[0]
    opts = analyst.prepare(
        case=case, testimony=testimony, solved=[], tried=set(), id_prefix="Q01", seed="s-1"
    )
    strong = [o for o in opts if o.strength == "strong"]
    assert [(o.line_id, o.evidence_id, o.contradiction_id) for o in strong] == [
        ("TS-01-2", "CE-01", "X-01")
    ]
    traps = [o for o in opts if o.strength == "trap"]
    assert [o.evidence_id for o in traps] == ["CE-03"]
    assert traps[0].trap_reason
    assert len([o for o in opts if o.strength == "weak"]) == TRIAL_MODE.distractor_options
    assert len([o for o in opts if o.kind == "probe"]) == TRIAL_MODE.probe_options
    assert len({o.id for o in opts}) == len(opts)
    assert all(o.id.startswith("Q01-") for o in opts)
    assert "つきつける" in strong[0].label

    again = analyst.prepare(
        case=case, testimony=testimony, solved=[], tried=set(), id_prefix="Q01", seed="s-1"
    )
    assert again == opts  # 同じ seed なら同じ順

    tried = {("present", "TS-01-2", "CE-03"), ("probe", "TS-01-1", None)}
    rest = analyst.prepare(
        case=case, testimony=testimony, solved=[], tried=tried, id_prefix="Q02", seed="s-2"
    )
    assert not [o for o in rest if o.strength == "trap"]
    assert ("probe", "TS-01-1") not in {(o.kind, o.line_id) for o in rest}


def test_redacted_option_hides_answer(case: Case) -> None:
    opts = TrialAnalyst(TRIAL_MODE).prepare(
        case=case, testimony=case.testimonies[0], solved=[], tried=set(), id_prefix="Q", seed="x"
    )
    for o in opts:
        r = o.redacted()
        assert r.strength is None and r.contradiction_id is None and r.trap_reason is None


def test_deviations_of() -> None:
    assert deviations_of(confessed=True, leaked=[], should_collapse=False) == [
        "premature_confession"
    ]
    assert deviations_of(confessed=False, leaked=[], should_collapse=True) == ["failed_collapse"]
    assert deviations_of(confessed=False, leaked=[0], should_collapse=False) == ["leak"]
    assert deviations_of(confessed=True, leaked=[0], should_collapse=True) == []


# --- 進行 ---


async def test_full_trial(prompts: PromptLoader, store: EventStore, case: Case) -> None:
    engine, responder = make_engine(prompts, store)
    session_id = await engine.start(case)
    state = engine.state
    assert state.stage == "choosing"
    assert state.testimony_id == case.testimonies[0].id
    assert state.penalty_gauge == TRIAL_MODE.penalty_gauge
    assert state.models == {"witness": "big", "judge": "big"}

    # ゆさぶる: 減点なし、証人は言い逃れる
    await engine.choose(find(engine, None, "probe").id)
    assert engine.state.penalty_gauge == TRIAL_MODE.penalty_gauge
    response = engine.state.responses[-1]
    assert response.text == EVADE_TEXT and not response.should_collapse
    assert response.check is not None and response.check.deviations == []
    assert response.call_id is not None

    # 罠: 減点 2
    await engine.choose(find(engine, "trap").id)
    assert engine.state.penalty_gauge == TRIAL_MODE.penalty_gauge - 2
    assert engine.state.stage == "choosing"

    # 正解: 崩れて、次の証言へ
    await engine.choose(find(engine, "strong").id)
    assert engine.state.solved == ["X-01"]
    assert engine.state.responses[-1].text == COLLAPSE_TEXT
    assert engine.state.responses[-1].should_collapse
    assert engine.state.testimony_id == case.testimonies[1].id

    witness_prompts = [user_text(r) for r in responder.requests["text"]]
    assert "決定的なもの" not in witness_prompts[0]
    assert "決定的なもの" in witness_prompts[2]
    assert "黙り込む" in witness_prompts[2]  # 台本の反応
    assert "これまでのやりとり" in witness_prompts[2]
    systems = [r.messages[0].content for r in responder.requests["text"]]
    assert "速報を読んでいる" in systems[0]  # 隠している事実は台本として渡す

    # 全矛盾を解いたら、最後の問いを出さずに閉廷する(ADR 0020)
    await engine.choose(find(engine, "strong").id)
    state = engine.state
    assert state.result == "solved" and state.stage == "finished"
    assert state.pending_choices is None and state.answer is None
    with pytest.raises(SessionStateError):
        await engine.advance()
    with pytest.raises(SessionStateError):
        await engine.answer(case.question.answer_index)

    await engine.object("learning_point", "LP-01", "出典の引用が古い気がします")
    await engine.object("trap", trap_target_id("X-01", "CE-03"), "罠が紛らわしすぎる")
    assert [o.target_id for o in engine.state.objections] == ["LP-01", "X-01/CE-03"]

    # ログだけで同じ状態を再構築できる
    replayed = TrialState.from_events(await store.load(session_id))
    assert replayed == engine.state
    resumed, _ = make_engine(prompts, store)
    assert await resumed.resume(session_id) == engine.state


async def test_legacy_session_waiting_for_the_question_can_still_answer(
    prompts: PromptLoader, store: EventStore, case: Case
) -> None:
    """全矛盾を解いて最後の問いの回答待ちで止まっている、以前のセッションは答えて閉廷できる。"""
    engine, _ = make_engine(prompts, store)
    session_id = await engine.start(case)
    for _ in case.contradictions:
        await engine.choose(find(engine, "strong").id)
    for event in await store.load(session_id):
        if not isinstance(event, TrialFinished):
            await store.append("legacy", event)
    legacy, _ = make_engine(prompts, store)
    assert (await legacy.resume("legacy")).stage == "answering"
    wrong = (case.question.answer_index + 1) % len(case.question.options)
    assert not await legacy.answer(wrong)
    assert legacy.state.result == "wrong_answer"


async def test_penalty_ends_trial(prompts: PromptLoader, store: EventStore, case: Case) -> None:
    engine, _ = make_engine(prompts, store, mode=TrialMode(penalty_gauge=2))
    await engine.start(case)
    await engine.choose(find(engine, "trap").id)
    state = engine.state
    assert state.penalty_gauge == 0
    assert state.result == "penalty"
    assert len(state.responses) == 1  # 証人の反論は聞いてから閉廷する
    with pytest.raises(SessionStateError):
        await engine.answer(0)
    await engine.object("contradiction", "X-02", "解説が分かりにくい")


async def test_deviation_detected(prompts: PromptLoader, store: EventStore, case: Case) -> None:
    engine, _ = make_engine(prompts, store, TrialResponder(confess_always=True, leak=True))
    await engine.start(case)
    await engine.choose(find(engine, None, "probe").id)
    check = engine.state.responses[-1].check
    assert check is not None
    assert check.confessed
    assert check.leaked_fact_indices == [0]  # 範囲外の番号は捨てる
    assert check.deviations == ["premature_confession", "leak"]


async def test_deviation_check_can_be_disabled(
    prompts: PromptLoader, store: EventStore, case: Case
) -> None:
    engine, responder = make_engine(prompts, store, mode=TrialMode(check_deviations=False))
    await engine.start(case)
    await engine.choose(find(engine, None, "probe").id)
    assert engine.state.responses[-1].check is None
    assert "DeviationOutput" not in responder.requests
    assert "judge" not in engine.state.models


async def test_invalid_operations(prompts: PromptLoader, store: EventStore, case: Case) -> None:
    engine, _ = make_engine(prompts, store)
    await engine.start(case)
    with pytest.raises(InvalidChoiceError):
        await engine.choose("Q99-1")
    with pytest.raises(SessionStateError):
        await engine.answer(0)
    with pytest.raises(SessionStateError):
        await engine.object("learning_point", "LP-01", "早すぎる")
    with pytest.raises(SessionStateError):
        await engine.advance()
    for _ in case.contradictions:
        await engine.choose(find(engine, "strong").id)
    assert engine.state.result == "solved"
    with pytest.raises(SessionStateError):
        await engine.answer(0)
    with pytest.raises(InvalidChoiceError):
        await engine.object("learning_point", "LP-99", "存在しない")
    with pytest.raises(ValueError):
        await engine.object("learning_point", "LP-01", "  ")


async def test_empty_witness_aborts(prompts: PromptLoader, store: EventStore, case: Case) -> None:
    class Silent(TrialResponder):
        def __call__(self, request: ChatRequest) -> FakeResponse:
            return FakeResponse.text("")

    engine, _ = make_engine(prompts, store, Silent())
    await engine.start(case)
    with pytest.raises(TrialError, match="空"):
        await engine.choose(find(engine, None, "probe").id)
    assert engine.state.aborted is not None
    assert engine.state.stage == "finished"


# --- 状態 ---


async def test_state_rejects_invalid_events(
    prompts: PromptLoader, store: EventStore, case: Case
) -> None:
    engine, _ = make_engine(prompts, store)
    await engine.start(case)
    state = engine.state
    foreign = TrialOption(id="Z-1", kind="probe", line_id="TS-01-1", label="x")
    with pytest.raises(InvalidEventError):
        state.apply(TrialChoiceMade(option=foreign))
    with pytest.raises(InvalidEventError):
        state.apply(ContradictionSolved(contradiction_id="X-01"))
    with pytest.raises(InvalidEventError):
        state.apply(AnswerSubmitted(index=0, correct=True))


# --- 解説 ---


def test_explanation_from_case_data(case: Case) -> None:
    explanation = build_explanation(case)
    assert explanation.answer == case.question.options[case.question.answer_index]
    assert [i.contradiction_id for i in explanation.items] == ["X-01", "X-02"]
    first = explanation.items[0]
    assert first.witness_name == "白波 恵"
    assert first.evidence_name == "実験結果の速報"
    assert first.traps[0].evidence_id == "CE-03"
    assert first.traps[0].misconception == "給付を受けると誰も働かなくなる"
    assert all(lp.sources for lp in explanation.learning_points)
