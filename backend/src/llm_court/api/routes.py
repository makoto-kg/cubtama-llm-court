"""REST と SSE のエンドポイント。"""

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request, status
from fastapi.responses import PlainTextResponse, StreamingResponse

from llm_court.api.context import ApiContext
from llm_court.api.schemas import (
    CreateSessionRequest,
    ErrorResponse,
    SessionListItem,
    SessionView,
    TaskAccepted,
    session_status,
    session_view,
)
from llm_court.api.sse import session_stream
from llm_court.api.tasks import TaskKind
from llm_court.domain import Event, ResearchReport
from llm_court.engine.debate import (
    DebateEngine,
    SessionNotFoundError,
    SessionStateError,
    next_step,
)
from llm_court.engine.record import render_markdown
from llm_court.engine.state import DebateState
from llm_court.engine.summary import DebateSummary, summarize

router = APIRouter(prefix="/api")

_ERRORS: dict[int | str, dict[str, object]] = {
    404: {"model": ErrorResponse, "description": "セッションがない"},
    409: {"model": ErrorResponse, "description": "現在の状態ではその操作をできない"},
}


EngineAction = Callable[[DebateEngine], Awaitable[None]]


def get_ctx(request: Request) -> ApiContext:
    ctx: ApiContext = request.app.state.ctx
    return ctx


Ctx = Annotated[ApiContext, Depends(get_ctx)]


async def _load(ctx: ApiContext, session_id: str) -> DebateState:
    events = await ctx.store.load(session_id)
    if not events:
        raise SessionNotFoundError(session_id)
    return DebateState.from_events(events)


def _view(ctx: ApiContext, state: DebateState) -> SessionView:
    assert state.session_id is not None
    return session_view(state, ctx.mode, ctx.tasks.running(state.session_id))


def _ensure_idle(ctx: ApiContext, session_id: str) -> None:
    task = ctx.tasks.running(session_id)
    if task is not None:
        raise SessionStateError(f"タスク({task.kind})が実行中です")


def _start_task(
    ctx: ApiContext, session_id: str, kind: TaskKind, action: EngineAction
) -> TaskAccepted:
    async def job() -> None:
        # 実行時に状態を読み直す(受付から開始までに状態が変わっていてもずれないように)
        engine = ctx.engine()
        with ctx.recorder.isolated():
            await engine.resume(session_id)
            await action(engine)

    return TaskAccepted(session_id=session_id, task=ctx.tasks.start(session_id, kind, job))


async def _research(engine: DebateEngine) -> None:
    await engine.collect_evidence(None)


async def _advance(engine: DebateEngine) -> None:
    await engine.advance()


async def _run_to_end(engine: DebateEngine) -> None:
    await engine.run_to_end()


@router.get("/health", operation_id="health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post(
    "/sessions",
    operation_id="createSession",
    status_code=status.HTTP_201_CREATED,
    tags=["sessions"],
)
async def create_session(body: CreateSessionRequest, ctx: Ctx) -> SessionView:
    """開廷する。続けて証拠品を用意する(`research` または `evidence`)。"""
    engine = ctx.engine()
    await engine.start(body.topic, body.rounds)
    return _view(ctx, engine.state)


@router.get("/sessions", operation_id="listSessions", tags=["sessions"])
async def list_sessions(ctx: Ctx) -> list[SessionListItem]:
    items: list[SessionListItem] = []
    for session_id in await ctx.store.list_sessions():
        events = await ctx.store.load(session_id)
        state = DebateState.from_events(events)
        assert state.topic is not None
        items.append(
            SessionListItem(
                session_id=session_id,
                topic=state.topic,
                status=session_status(state),
                created_at=events[0].timestamp,
            )
        )
    return items


@router.get(
    "/sessions/{session_id}", operation_id="getSession", tags=["sessions"], responses=_ERRORS
)
async def get_session(session_id: str, ctx: Ctx) -> SessionView:
    return _view(ctx, await _load(ctx, session_id))


@router.post(
    "/sessions/{session_id}/research",
    operation_id="startResearch",
    status_code=status.HTTP_202_ACCEPTED,
    tags=["progress"],
    responses=_ERRORS,
)
async def start_research(session_id: str, ctx: Ctx) -> TaskAccepted:
    """捜査をバックグラウンドで始める。進捗と結果は SSE で通知する。"""
    state = await _load(ctx, session_id)
    _ensure_idle(ctx, session_id)
    if state.finished:
        raise SessionStateError("閉廷しています")
    if state.research is not None:
        raise SessionStateError("証拠品はすでに集まっています")
    return _start_task(ctx, session_id, "research", _research)


@router.put(
    "/sessions/{session_id}/evidence",
    operation_id="setEvidence",
    tags=["progress"],
    responses=_ERRORS,
)
async def set_evidence(session_id: str, report: ResearchReport, ctx: Ctx) -> SessionView:
    """既存の捜査結果(`llm-court research` の JSON)を証拠品として使い、捜査を省略する。"""
    await _load(ctx, session_id)
    _ensure_idle(ctx, session_id)
    engine = ctx.engine()
    await engine.resume(session_id)
    await engine.collect_evidence(report)
    return _view(ctx, engine.state)


def _ensure_can_advance(state: DebateState, ctx: ApiContext) -> None:
    if next_step(state, ctx.mode) is None:
        if state.finished:
            raise SessionStateError("閉廷しています")
        raise SessionStateError("証拠品がまだありません")


@router.post(
    "/sessions/{session_id}/advance",
    operation_id="advanceSession",
    status_code=status.HTTP_202_ACCEPTED,
    tags=["progress"],
    responses=_ERRORS,
)
async def advance_session(session_id: str, ctx: Ctx) -> TaskAccepted:
    """次の 1 手(発言または判決)をバックグラウンドで進める。発言は SSE でストリーミングする。"""
    state = await _load(ctx, session_id)
    _ensure_idle(ctx, session_id)
    _ensure_can_advance(state, ctx)
    return _start_task(ctx, session_id, "advance", _advance)


@router.post(
    "/sessions/{session_id}/run",
    operation_id="runSession",
    status_code=status.HTTP_202_ACCEPTED,
    tags=["progress"],
    responses=_ERRORS,
)
async def run_session(session_id: str, ctx: Ctx) -> TaskAccepted:
    """判決まで自動で進める。"""
    state = await _load(ctx, session_id)
    _ensure_idle(ctx, session_id)
    _ensure_can_advance(state, ctx)
    return _start_task(ctx, session_id, "run", _run_to_end)


@router.get(
    "/sessions/{session_id}/events",
    operation_id="listEvents",
    tags=["logs"],
    responses=_ERRORS,
)
async def list_events(
    session_id: str, ctx: Ctx, after: Annotated[int, Query(ge=0)] = 0
) -> list[Event]:
    """イベントログ(`after` より後の seq)。"""
    events = await ctx.store.load(session_id)
    if not events:
        raise SessionNotFoundError(session_id)
    return [e for e in events if e.seq > after]


@router.get(
    "/sessions/{session_id}/stream",
    operation_id="streamSession",
    tags=["logs"],
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {"text/event-stream": {}},
            "description": (
                "SSE。event は debate(永続イベント、id=seq)/ turn(発言開始)/ "
                "token(発言のチャンク)/ progress / task。判決・中断で終わる"
            ),
        },
        **_ERRORS,
    },
)
async def stream_session(
    session_id: str,
    ctx: Ctx,
    after: Annotated[int, Query(ge=0)] = 0,
    last_event_id: Annotated[str | None, Header()] = None,
) -> StreamingResponse:
    await _load(ctx, session_id)
    if last_event_id is not None and last_event_id.isdigit():
        after = max(after, int(last_event_id))
    return StreamingResponse(
        session_stream(
            session_id=session_id,
            after=after,
            store=ctx.store,
            hub=ctx.hub,
            keepalive_s=ctx.settings.api_sse_keepalive_s,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get(
    "/sessions/{session_id}/record",
    operation_id="getRecord",
    tags=["logs"],
    response_class=PlainTextResponse,
    responses={200: {"content": {"text/markdown": {}}}, **_ERRORS},
)
async def get_record(session_id: str, ctx: Ctx) -> PlainTextResponse:
    """人間が読める Markdown の法廷記録。"""
    state = await _load(ctx, session_id)
    return PlainTextResponse(render_markdown(state, ctx.mode), media_type="text/markdown")


@router.get(
    "/sessions/{session_id}/summary",
    operation_id="getSummary",
    tags=["logs"],
    responses=_ERRORS,
)
async def get_summary(session_id: str, ctx: Ctx) -> DebateSummary:
    """計測サマリ(ターンごとの待ち時間、トークン、構造化出力の失敗、出典の問題)。"""
    events = await ctx.store.load(session_id)
    if not events:
        raise SessionNotFoundError(session_id)
    return summarize(events)
