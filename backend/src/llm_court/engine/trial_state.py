"""イベント列からの裁判(裁判型のプレイ)の状態の再構築。"""

from collections.abc import Iterable
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict

from llm_court.domain import (
    AnswerSubmitted,
    Case,
    Contradiction,
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
    TrialResult,
    TrialStarted,
    WitnessResponded,
)
from llm_court.engine.state import InvalidEventError

TrialStage = Literal["examining", "choosing", "responding", "answering", "finished"]
"""examining: 選択肢の用意待ち / choosing: プレイヤーの選択待ち / responding: 証人の応答待ち /
answering: 最後の問いの回答待ち / finished: 閉廷(中断を含む)。"""


class TrialState(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: str | None = None
    case: Case | None = None
    models: dict[str, str] = {}
    penalty_gauge: int = 0
    penalty_gauge_max: int = 0
    testimony_id: str | None = None
    """尋問中の証言。"""
    pending_choices: TrialChoicesPrepared | None = None
    choices: list[TrialChoiceMade] = []
    responses: list[WitnessResponded] = []
    solved: list[str] = []
    """解いた矛盾の ID(解いた順)。"""
    answer: AnswerSubmitted | None = None
    result: TrialResult | None = None
    aborted: str | None = None
    objections: list[ExplanationObjected] = []
    llm_calls: list[LLMCallInfo] = []
    last_seq: int = 0

    @classmethod
    def from_events(cls, events: Iterable[Event]) -> Self:
        state = cls()
        for event in events:
            state = state.apply(event)
        return state

    @property
    def finished(self) -> bool:
        return self.result is not None or self.aborted is not None

    @property
    def all_solved(self) -> bool:
        return self.case is not None and len(self.solved) == len(self.case.contradictions)

    @property
    def stage(self) -> TrialStage:
        if self.finished:
            return "finished"
        if self.all_solved:
            return "answering"
        if self.pending_choices is not None:
            return "choosing"
        if len(self.choices) > len(self.responses):
            return "responding"
        return "examining"

    @property
    def testimony(self) -> Testimony | None:
        if self.case is None or self.testimony_id is None:
            return None
        return next((t for t in self.case.testimonies if t.id == self.testimony_id), None)

    def unsolved_in(self, testimony: Testimony) -> list[Contradiction]:
        """その証言の、まだ解いていない矛盾。"""
        assert self.case is not None
        line_ids = {line.id for line in testimony.lines}
        return [
            c
            for c in self.case.contradictions
            if c.testimony_line_id in line_ids and c.id not in self.solved
        ]

    def next_testimony(self) -> Testimony | None:
        """次に尋問する証言(まだ解いていない矛盾がある最初の証言)。"""
        if self.case is None:
            return None
        return next((t for t in self.case.testimonies if self.unsolved_in(t)), None)

    @property
    def last_choice(self) -> TrialChoiceMade | None:
        return self.choices[-1] if self.choices else None

    def apply(self, event: Event) -> Self:
        """イベントを 1 件適用した新しい状態を返す(元の状態は変えない)。"""
        if event.seq and event.seq <= self.last_seq:
            raise InvalidEventError(f"seq が単調増加していません: {event.seq}")
        if not isinstance(event, TrialStarted) and self.session_id is None:
            raise InvalidEventError(f"開廷前のイベントです: {event.type}")
        if self.finished and not isinstance(event, LLMCallRecorded | ExplanationObjected):
            raise InvalidEventError(f"閉廷後のイベントです: {event.type}")

        update: dict[str, object] = {"last_seq": event.seq or self.last_seq}
        match event:
            case TrialStarted():
                if self.session_id is not None:
                    raise InvalidEventError("すでに開廷しています")
                update |= {
                    "session_id": event.session_id,
                    "case": event.case,
                    "models": event.models,
                    "penalty_gauge": event.penalty_gauge,
                    "penalty_gauge_max": event.penalty_gauge,
                }
            case TestimonyStarted():
                assert self.case is not None
                if event.testimony_id not in {t.id for t in self.case.testimonies}:
                    raise InvalidEventError(f"証言 {event.testimony_id} はありません")
                if self.stage != "examining":
                    raise InvalidEventError("尋問の途中で証言は変えられません")
                update["testimony_id"] = event.testimony_id
            case TrialChoicesPrepared():
                if event.testimony_id != self.testimony_id:
                    raise InvalidEventError("尋問中の証言と選択肢の証言が違います")
                if self.stage != "examining":
                    raise InvalidEventError("選択肢を用意できる状態ではありません")
                update["pending_choices"] = event
            case TrialChoiceMade():
                pending = self.pending_choices
                if pending is None or event.option not in pending.options:
                    raise InvalidEventError("示されていない選択肢は選べません")
                update |= {"pending_choices": None, "choices": [*self.choices, event]}
            case WitnessResponded():
                last = self.last_choice
                if self.stage != "responding" or last is None:
                    raise InvalidEventError("証人が応答する場面ではありません")
                if event.option_id != last.option.id:
                    raise InvalidEventError("直前の選択肢への応答ではありません")
                update["responses"] = [*self.responses, event]
            case ContradictionSolved():
                assert self.case is not None
                last = self.last_choice
                if last is None or last.option.contradiction_id != event.contradiction_id:
                    raise InvalidEventError("正解をつきつけていない矛盾は解けません")
                if event.contradiction_id in self.solved:
                    raise InvalidEventError("すでに解いた矛盾です")
                update["solved"] = [*self.solved, event.contradiction_id]
            case PenaltyApplied():
                update["penalty_gauge"] = event.remaining
            case AnswerSubmitted():
                if self.stage != "answering":
                    raise InvalidEventError("まだ最後の問いに答えられません")
                update["answer"] = event
            case TrialFinished():
                update["result"] = event.result
            case SessionAborted():
                update["aborted"] = event.reason
            case ExplanationObjected():
                if self.result is None:
                    raise InvalidEventError("解説への異議は閉廷後に送れます")
                update["objections"] = [*self.objections, event]
            case LLMCallRecorded():
                update["llm_calls"] = [*self.llm_calls, event.call]
            case _:
                raise InvalidEventError(f"裁判では扱わないイベントです: {event.type}")
        return self.model_copy(update=update)
