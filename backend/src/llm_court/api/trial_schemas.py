"""裁判(裁判型のプレイ)の API のリクエスト・レスポンスのモデル。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from llm_court.api.tasks import TaskView
from llm_court.domain import (
    Case,
    CasePublic,
    DeviationCheck,
    Explanation,
    ExplanationObjected,
    TrialOption,
    TrialResult,
)
from llm_court.engine.explanation import build_explanation
from llm_court.engine.trial import ObjectionTarget
from llm_court.engine.trial_state import TrialStage, TrialState
from llm_court.modes import TrialMode

TrialStatus = Literal["in_progress", "answering", "finished", "aborted"]


class CaseSummary(BaseModel):
    """事件の一覧の 1 件(公開の情報と検証の結果だけ)。"""

    model_config = ConfigDict(frozen=True)

    id: str
    title: str
    theme: str
    overview: str
    witnesses: int
    testimonies: int
    contradictions: int
    solvable: bool
    solve_rate: float | None
    created_at: datetime


def case_summary(case: Case) -> CaseSummary:
    v = case.validation
    return CaseSummary(
        id=case.id,
        title=case.title,
        theme=case.theme,
        overview=case.overview,
        witnesses=len({t.witness_id for t in case.testimonies}),
        testimonies=len(case.testimonies),
        contradictions=len(case.contradictions),
        solvable=bool(v and v.solved),
        solve_rate=v.solve_rate if v else None,
        created_at=case.created_at,
    )


class CreateTrialRequest(BaseModel):
    case_id: str = Field(min_length=1, description="遊ぶ事件の ID")


class AnswerRequest(BaseModel):
    index: int = Field(ge=0, description="最後の問いの選択肢の番号(0 始まり)")


class ObjectionRequest(BaseModel):
    target_kind: ObjectionTarget
    target_id: str = Field(
        min_length=1,
        description="学習ポイント・矛盾の ID、罠は「矛盾の ID/証拠品の ID」",
    )
    comment: str = Field(min_length=1, max_length=1000)


class TrialExchange(BaseModel):
    """尋問の 1 往復(選んだ選択肢と証人の応答)。"""

    model_config = ConfigDict(frozen=True)

    option: TrialOption
    """選んだ選択肢(強さを公開)。"""
    witness_id: str
    text: str
    solved: bool
    penalty: int
    check: DeviationCheck | None
    """台本からの逸脱の判定(閉廷後だけ公開)。"""


class TrialView(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: str
    case: CasePublic
    status: TrialStatus
    stage: TrialStage
    running_task: TaskView | None
    models: dict[str, str]
    testimony_id: str | None
    pending_options: list[TrialOption]
    """選択待ちの選択肢(強さは伏せてある)。"""
    exchanges: list[TrialExchange]
    solved_line_ids: list[str]
    """解いた(崩した)証言の行。"""
    solved_count: int
    contradiction_count: int
    penalty_gauge: int
    penalty_gauge_max: int
    answer_index: int | None
    answer_correct: bool | None
    result: TrialResult | None
    aborted: str | None
    explanation: Explanation | None
    """閉廷後の解説(閉廷前は None)。"""
    objections: list[ExplanationObjected]


def trial_status(state: TrialState) -> TrialStatus:
    if state.aborted is not None:
        return "aborted"
    if state.result is not None:
        return "finished"
    return "answering" if state.stage == "answering" else "in_progress"


def trial_view(state: TrialState, mode: TrialMode, task: TaskView | None) -> TrialView:
    case = state.case
    assert state.session_id is not None and case is not None
    revealed = state.finished
    contradictions = {c.id: c for c in case.contradictions}
    exchanges: list[TrialExchange] = []
    for choice, response in zip(state.choices, state.responses, strict=False):
        cid = choice.option.contradiction_id
        exchanges.append(
            TrialExchange(
                option=choice.option,
                witness_id=response.witness_id,
                text=response.text,
                solved=cid is not None,
                penalty=mode.penalty_for(choice.option.strength),
                check=response.check if revealed else None,
            )
        )
    pending = state.pending_choices
    answer = state.answer
    return TrialView(
        session_id=state.session_id,
        case=case.public_view(),
        status=trial_status(state),
        stage=state.stage,
        running_task=task,
        models=state.models,
        testimony_id=state.testimony_id,
        pending_options=[o.redacted() for o in pending.options] if pending else [],
        exchanges=exchanges,
        solved_line_ids=[
            contradictions[cid].testimony_line_id for cid in state.solved if cid in contradictions
        ],
        solved_count=len(state.solved),
        contradiction_count=len(case.contradictions),
        penalty_gauge=state.penalty_gauge,
        penalty_gauge_max=state.penalty_gauge_max,
        answer_index=answer.index if answer else None,
        answer_correct=answer.correct if answer else None,
        result=state.result,
        aborted=state.aborted,
        explanation=build_explanation(case) if state.result is not None else None,
        objections=state.objections,
    )
