"""裁判(裁判型のプレイ)の進行エンジン。

開廷 → 証言ごとの尋問(選択肢 → 証人の応答 → 逸脱の検査)→ 最後の問い → 閉廷 → 解説 の順に
進める。状態はイベントをストアに追記した結果としてのみ変わる(`TrialState.apply`)。
"""

import asyncio
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Literal

from llm_court.agents.deviation import DeviationChecker
from llm_court.agents.trial_analyst import TrialAnalyst
from llm_court.agents.witness import Exchange, WitnessAgent
from llm_court.config import Role
from llm_court.domain import (
    AnswerSubmitted,
    Case,
    ContradictionSolved,
    Event,
    ExplanationObjected,
    LLMCallInfo,
    LLMCallRecorded,
    PenaltyApplied,
    SessionAborted,
    Testimony,
    TestimonyStarted,
    TrialChoiceMade,
    TrialChoicesPrepared,
    TrialFinished,
    TrialOption,
    TrialStarted,
    WitnessResponded,
)
from llm_court.engine.debate import (
    DebateError,
    InvalidChoiceError,
    SessionNotFoundError,
    SessionStateError,
)
from llm_court.engine.recorder import BufferedRecorder
from llm_court.engine.store import EventStore
from llm_court.engine.trial_state import TrialState
from llm_court.llm import LLMClient, PromptLoader
from llm_court.modes import TrialMode

ObjectionTarget = Literal["learning_point", "contradiction", "trap"]


class TrialError(DebateError):
    """裁判を続行できない。"""


class TrialObserver:
    """進行の通知を受ける(CLI・API での表示用)。既定は何もしない。"""

    def on_event(self, event: Event) -> None:
        pass

    def on_progress(self, message: str) -> None:
        pass

    def on_witness_start(self, witness_id: str) -> None:
        pass

    def on_witness_token(self, witness_id: str, chunk: str) -> None:
        pass


def trap_target_id(contradiction_id: str, evidence_id: str) -> str:
    """「解説に異議あり」で罠を指すときの ID。"""
    return f"{contradiction_id}/{evidence_id}"


class TrialEngine:
    def __init__(
        self,
        *,
        llm: LLMClient,
        recorder: BufferedRecorder,
        prompts: PromptLoader,
        store: EventStore,
        mode: TrialMode,
        observer: TrialObserver | None = None,
    ) -> None:
        self._llm = llm
        self._recorder = recorder
        self._store = store
        self._mode = mode
        self._observer = observer or TrialObserver()
        self._analyst = TrialAnalyst(mode)
        self._witness = WitnessAgent(llm, prompts)
        self._checker = DeviationChecker(llm, prompts)
        self.session_id = ""
        self.state = TrialState()

    def set_observer(self, observer: TrialObserver) -> None:
        self._observer = observer

    # --- イベント ---

    async def _emit(self, event: Event) -> Event:
        stored = await self._store.append(self.session_id, event)
        self.state = self.state.apply(stored)
        self._observer.on_event(stored)
        return stored

    async def _emit_calls(self, calls: list[LLMCallInfo]) -> None:
        for call in calls:
            await self._emit(
                LLMCallRecorded(
                    call=call, role=call.role, model=call.model, prompt_version=call.prompt_version
                )
            )

    async def _flush_llm_calls(self) -> None:
        await self._emit_calls(self._recorder.drain())

    def _model(self, role: Role) -> str:
        return self._llm.config.resolve(role).model.model

    @property
    def _case(self) -> Case:
        case = self.state.case
        if case is None:
            raise SessionStateError("開廷していません")
        return case

    # --- 操作 ---

    async def start(self, case: Case) -> str:
        """開廷し、最初の証言の選択肢まで用意する。セッション ID を返す。"""
        if not case.contradictions:
            raise ValueError("矛盾のない事件は遊べません")
        roles = [Role.WITNESS] + ([Role.JUDGE] if self._mode.check_deviations else [])
        self.session_id = uuid.uuid4().hex[:12]
        self.state = TrialState()
        await self._emit(
            TrialStarted(
                case=case,
                models={role.value: self._model(role) for role in roles},
                penalty_gauge=self._mode.penalty_gauge,
            )
        )
        async with self._abort_on_error():
            await self._next()
        return self.session_id

    async def resume(self, session_id: str) -> TrialState:
        events = await self._store.load(session_id)
        if not events:
            raise SessionNotFoundError(session_id)
        self.session_id = session_id
        self.state = TrialState.from_events(events)
        return self.state

    async def advance(self) -> None:
        """選択肢の用意待ちなら用意する(応答の途中で中断した場合などの回復用)。"""
        if self.state.stage != "examining":
            raise SessionStateError(f"進められる状態ではありません({self.state.stage})")
        async with self._abort_on_error():
            await self._next()

    async def choose(self, option_id: str) -> None:
        """選択肢を選び、証人に応答させ、次の選択肢(または最後の問い)まで進める。"""
        pending = self.state.pending_choices
        if self.state.stage != "choosing" or pending is None:
            raise SessionStateError("選択を受け付ける場面ではありません")
        option = next((o for o in pending.options if o.id == option_id), None)
        if option is None:
            raise InvalidChoiceError(f"選択肢 {option_id} はありません")
        testimony = self.state.testimony
        assert testimony is not None
        async with self._abort_on_error():
            await self._emit(TrialChoiceMade(option=option))
            penalty = self._mode.penalty_for(option.strength)
            if penalty:
                await self._emit(
                    PenaltyApplied(
                        amount=penalty,
                        remaining=self.state.penalty_gauge - penalty,
                        reason=f"{option.strength} の組をつきつけた",
                    )
                )
            await self._respond(testimony, option)
            if option.contradiction_id is not None:
                await self._emit(ContradictionSolved(contradiction_id=option.contradiction_id))
            if self.state.penalty_gauge <= 0:
                await self._emit(TrialFinished(result="penalty"))
                return
            await self._next()

    async def answer(self, index: int) -> bool:
        """最後の問いに答えて閉廷する。正答なら True。"""
        if self.state.stage != "answering":
            raise SessionStateError("最後の問いに答える場面ではありません")
        question = self._case.question
        if not 0 <= index < len(question.options):
            raise InvalidChoiceError(f"選択肢 {index} はありません")
        correct = index == question.answer_index
        await self._emit(AnswerSubmitted(index=index, correct=correct))
        await self._emit(TrialFinished(result="solved" if correct else "wrong_answer"))
        return correct

    async def object(self, target_kind: ObjectionTarget, target_id: str, comment: str) -> None:
        """解説の項目に異議を記録する(閉廷後のみ)。"""
        if self.state.result is None:
            raise SessionStateError("解説への異議は閉廷後に送れます")
        case = self._case
        known: set[str]
        match target_kind:
            case "learning_point":
                known = {lp.id for lp in case.learning_points}
            case "contradiction":
                known = {c.id for c in case.contradictions}
            case "trap":
                known = {
                    trap_target_id(c.id, t.evidence_id)
                    for c in case.contradictions
                    for t in c.traps
                }
        if target_id not in known:
            raise InvalidChoiceError(f"解説の項目 {target_id} はありません")
        if not comment.strip():
            raise ValueError("コメントが空です")
        await self._emit(
            ExplanationObjected(target_kind=target_kind, target_id=target_id, comment=comment)
        )

    # --- 進行 ---

    async def _next(self) -> None:
        """次の証言に入り、選択肢を用意する。全矛盾を解いていれば何もしない(問いの回答待ち)。"""
        state = self.state
        if state.stage != "examining":
            return
        testimony = state.testimony
        if testimony is None or not state.unsolved_in(testimony):
            testimony = state.next_testimony()
            if testimony is None:
                return
            await self._emit(TestimonyStarted(testimony_id=testimony.id))
        await self._prepare_choices(testimony)

    async def _prepare_choices(self, testimony: Testimony) -> None:
        state = self.state
        number = len(state.choices) + 1
        options = self._analyst.prepare(
            case=self._case,
            testimony=testimony,
            solved=state.solved,
            tried={(c.option.kind, c.option.line_id, c.option.evidence_id) for c in state.choices},
            id_prefix=f"Q{number:02d}",
            seed=f"{self.session_id}-{number}",
        )
        await self._emit(
            TrialChoicesPrepared(
                testimony_id=testimony.id, options=options, role=Role.ANALYST.value
            )
        )

    def _history(self, testimony: Testimony) -> list[Exchange]:
        line_ids = {line.id for line in testimony.lines}
        return [
            Exchange(action=choice.option.label, text=response.text)
            for choice, response in zip(self.state.choices, self.state.responses, strict=False)
            if choice.option.line_id in line_ids
        ]

    async def _respond(self, testimony: Testimony, option: TrialOption) -> None:
        case = self._case
        prompt = self._witness.build_prompt(
            case=case, testimony=testimony, option=option, history=self._history(testimony)
        )
        witness_id = testimony.witness_id
        self._observer.on_witness_start(witness_id)
        parts: list[str] = []
        async for chunk in self._witness.stream(prompt):
            parts.append(chunk)
            self._observer.on_witness_token(witness_id, chunk)
        calls = self._recorder.drain()
        await self._emit_calls(calls)
        text = "".join(parts).strip()
        if not text:
            raise TrialError("被告の応答が空でした")
        should_collapse = option.contradiction_id is not None
        check = None
        if self._mode.check_deviations:
            self._observer.on_progress("被告の応答を確かめています")
            check = await self._checker.check(
                case=case,
                testimony=testimony,
                option=option,
                response=text,
                should_collapse=should_collapse,
            )
            await self._flush_llm_calls()
        await self._emit(
            WitnessResponded(
                option_id=option.id,
                witness_id=witness_id,
                text=text,
                should_collapse=should_collapse,
                check=check,
                call_id=calls[-1].call_id if calls else None,
                role=Role.WITNESS.value,
                model=self._model(Role.WITNESS),
                prompt_version=prompt.version,
            )
        )

    @asynccontextmanager
    async def _abort_on_error(self) -> AsyncGenerator[None]:
        """処理中の例外は `SessionAborted` として記録してから送出する。"""
        try:
            yield
        except asyncio.CancelledError:
            await self._flush_llm_calls()
            await self._emit(SessionAborted(reason="中断されました"))
            raise
        except Exception as e:
            await self._flush_llm_calls()
            await self._emit(SessionAborted(reason=f"{type(e).__name__}: {e}"))
            raise
