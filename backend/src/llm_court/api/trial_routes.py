"""裁判(裁判型のプレイ)のエンドポイント。

イベントログと SSE はディベートと共通(`/api/sessions/{id}/events`、`/api/sessions/{id}/stream`)。
"""

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from llm_court.api.context import ApiContext
from llm_court.api.routes import Ctx
from llm_court.api.schemas import ChooseRequest, ErrorResponse, TaskAccepted
from llm_court.api.tasks import TaskKind
from llm_court.api.trial_schemas import (
    AnswerRequest,
    CaseSummary,
    CreateTrialRequest,
    ObjectionRequest,
    TrialView,
    case_summary,
    trial_view,
)
from llm_court.domain import TrialStarted
from llm_court.engine.debate import InvalidChoiceError, SessionNotFoundError, SessionStateError
from llm_court.engine.trial import TrialEngine
from llm_court.engine.trial_state import TrialState

router = APIRouter(prefix="/api")

_ERRORS: dict[int | str, dict[str, object]] = {
    404: {"model": ErrorResponse, "description": "裁判・事件がない"},
    409: {"model": ErrorResponse, "description": "現在の状態ではその操作をできない"},
}
_CHOICE_ERRORS: dict[int | str, dict[str, object]] = {
    **_ERRORS,
    422: {"model": ErrorResponse, "description": "選択肢・項目がない"},
}

TrialAction = Callable[[TrialEngine], Awaitable[None]]


async def _load(ctx: ApiContext, session_id: str) -> TrialState:
    events = await ctx.store.load(session_id)
    if not events or not isinstance(events[0], TrialStarted):
        raise SessionNotFoundError(session_id)
    return TrialState.from_events(events)


def _view(ctx: ApiContext, state: TrialState) -> TrialView:
    assert state.session_id is not None
    return trial_view(state, ctx.trial_mode, ctx.tasks.running(state.session_id))


def _ensure_idle(ctx: ApiContext, session_id: str) -> None:
    task = ctx.tasks.running(session_id)
    if task is not None:
        raise SessionStateError(f"タスク({task.kind})が実行中です")


async def _engine(ctx: ApiContext, session_id: str) -> TrialEngine:
    engine = ctx.trial_engine()
    await engine.resume(session_id)
    return engine


def _start_task(
    ctx: ApiContext, session_id: str, kind: TaskKind, action: TrialAction
) -> TaskAccepted:
    async def job() -> None:
        with ctx.recorder.isolated():
            engine = await _engine(ctx, session_id)
            await action(engine)

    return TaskAccepted(session_id=session_id, task=ctx.tasks.start(session_id, kind, job))


@router.get("/cases", operation_id="listCases", tags=["trials"])
async def list_cases(
    ctx: Ctx,
    all_cases: Annotated[
        bool, Query(alias="all", description="解けると判定されていない事件も含める")
    ] = False,
) -> list[CaseSummary]:
    """遊べる事件の一覧(公開の情報だけ)。既定では solver の検証に合格した事件だけ。"""
    summaries = [case_summary(c) for c in ctx.cases.list()]
    return summaries if all_cases else [s for s in summaries if s.solvable]


@router.post(
    "/trials",
    operation_id="createTrial",
    status_code=status.HTTP_201_CREATED,
    tags=["trials"],
    responses=_ERRORS,
)
async def create_trial(body: CreateTrialRequest, ctx: Ctx) -> TrialView:
    """事件を選んで開廷する。最初の証言の選択肢まで用意して返す。"""
    case = ctx.cases.load(body.case_id)
    if not case.contradictions:
        raise HTTPException(status_code=409, detail="矛盾のない事件は遊べません")
    engine = ctx.trial_engine()
    await engine.start(case)
    return _view(ctx, engine.state)


@router.get("/trials/{session_id}", operation_id="getTrial", tags=["trials"], responses=_ERRORS)
async def get_trial(session_id: str, ctx: Ctx) -> TrialView:
    return _view(ctx, await _load(ctx, session_id))


async def _advance(engine: TrialEngine) -> None:
    await engine.advance()


@router.post(
    "/trials/{session_id}/advance",
    operation_id="advanceTrial",
    status_code=status.HTTP_202_ACCEPTED,
    tags=["trials"],
    responses=_ERRORS,
)
async def advance_trial(session_id: str, ctx: Ctx) -> TaskAccepted:
    """選択肢の用意待ちなら用意する(通常は選択のたびに自動で用意される)。"""
    state = await _load(ctx, session_id)
    _ensure_idle(ctx, session_id)
    if state.stage != "examining":
        raise SessionStateError(f"進められる状態ではありません({state.stage})")
    return _start_task(ctx, session_id, "advance", _advance)


@router.post(
    "/trials/{session_id}/choices",
    operation_id="chooseTrialOption",
    status_code=status.HTTP_202_ACCEPTED,
    tags=["trials"],
    responses=_CHOICE_ERRORS,
)
async def choose_trial_option(session_id: str, body: ChooseRequest, ctx: Ctx) -> TaskAccepted:
    """選択肢を選ぶ。証人の応答を SSE でストリーミングし、次の選択肢(または問い)まで進める。"""
    state = await _load(ctx, session_id)
    _ensure_idle(ctx, session_id)
    pending = state.pending_choices
    if state.stage != "choosing" or pending is None:
        raise SessionStateError("選択を受け付ける場面ではありません")
    if all(o.id != body.option_id for o in pending.options):
        raise InvalidChoiceError(f"選択肢 {body.option_id} はありません")
    option_id = body.option_id

    async def action(engine: TrialEngine) -> None:
        await engine.choose(option_id)

    return _start_task(ctx, session_id, "choice", action)


@router.post(
    "/trials/{session_id}/answer",
    operation_id="answerTrial",
    tags=["trials"],
    responses=_CHOICE_ERRORS,
)
async def answer_trial(session_id: str, body: AnswerRequest, ctx: Ctx) -> TrialView:
    """最後の問いに答えて閉廷する。閉廷後は解説を返す。"""
    await _load(ctx, session_id)
    _ensure_idle(ctx, session_id)
    engine = await _engine(ctx, session_id)
    await engine.answer(body.index)
    return _view(ctx, engine.state)


@router.post(
    "/trials/{session_id}/objections",
    operation_id="objectToExplanation",
    status_code=status.HTTP_201_CREATED,
    tags=["trials"],
    responses=_CHOICE_ERRORS,
)
async def object_to_explanation(session_id: str, body: ObjectionRequest, ctx: Ctx) -> TrialView:
    """「解説に異議あり」。解説の項目の誤りを報告する(閉廷後のみ)。"""
    await _load(ctx, session_id)
    if not body.comment.strip():
        raise HTTPException(status_code=422, detail="コメントが空です")
    engine = await _engine(ctx, session_id)
    await engine.object(body.target_kind, body.target_id, body.comment.strip())
    return _view(ctx, engine.state)
