"""REST と SSE のエンドポイント。"""

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse, StreamingResponse

from llm_court.api.context import ApiContext
from llm_court.api.redaction import redact_events
from llm_court.api.schemas import (
    ChoicesView,
    ChooseRequest,
    ConfigView,
    CreateSessionRequest,
    ErrorResponse,
    EvidenceSample,
    RoleAssignment,
    SessionListItem,
    SessionView,
    TaskAccepted,
    choices_view,
    session_status,
    session_view,
)
from llm_court.api.sse import session_stream
from llm_court.api.tasks import TaskKind
from llm_court.config import Role
from llm_court.domain import Event, ResearchReport
from llm_court.engine.debate import (
    DebateEngine,
    InvalidChoiceError,
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


def _choose(option_id: str) -> EngineAction:
    async def action(engine: DebateEngine) -> None:
        await engine.choose(option_id)
        # 次の人間の手番(選択肢を用意して止まる)か判決まで進める
        await engine.run_to_end()

    return action


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
    await engine.start(body.topic, body.rounds, human_side=body.human_side)
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


def _samples(ctx: ApiContext) -> dict[str, Path]:
    directory = ctx.settings.sample_evidence_dir
    if not directory.is_dir():
        return {}
    return {p.stem: p for p in sorted(directory.glob("*.json"))}


@router.get("/evidence-samples", operation_id="listEvidenceSamples", tags=["evidence"])
async def list_evidence_samples(ctx: Ctx) -> list[EvidenceSample]:
    """同梱の捜査結果の一覧。SearXNG なしで始めるときに使う。"""
    items: list[EvidenceSample] = []
    for name, path in _samples(ctx).items():
        report = ResearchReport.model_validate_json(path.read_text(encoding="utf-8"))
        items.append(
            EvidenceSample(
                name=name,
                topic=report.topic,
                evidence_count=len(report.evidence),
                created_at=report.created_at,
            )
        )
    return items


@router.post(
    "/sessions/{session_id}/evidence/samples/{name}",
    operation_id="useEvidenceSample",
    tags=["evidence"],
    responses=_ERRORS,
)
async def use_evidence_sample(session_id: str, name: str, ctx: Ctx) -> SessionView:
    """同梱の捜査結果を証拠品として使う。`name` は一覧にあるものだけ受け付ける。"""
    path = _samples(ctx).get(name)
    if path is None:
        raise HTTPException(status_code=404, detail=f"同梱の捜査結果 {name} はありません")
    report = ResearchReport.model_validate_json(path.read_text(encoding="utf-8"))
    return await set_evidence(session_id, report, ctx)


@router.get("/config", operation_id="getConfig", tags=["system"])
async def get_config(ctx: Ctx) -> ConfigView:
    """役割ごとのモデル割り当て(api_key は返さない)。"""
    config = ctx.llm.config
    roles: list[RoleAssignment] = []
    for role in Role:
        r = config.resolve(role)
        caps = r.provider.capabilities
        roles.append(
            RoleAssignment(
                role=role.value,
                model_key=r.model_key,
                model=r.model.model,
                reasoning=r.model.reasoning,
                provider=r.provider_key,
                base_url=r.provider.base_url,
                json_schema=caps.json_schema,
                json_mode=caps.json_mode,
                streaming=caps.streaming,
                max_concurrency=r.provider.max_concurrency,
            )
        )
    return ConfigView(roles=roles)


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
    "/sessions/{session_id}/choices",
    operation_id="getChoices",
    tags=["human"],
    responses=_ERRORS,
)
async def get_choices(session_id: str, ctx: Ctx) -> ChoicesView:
    """人間の手番の選択肢。強さ(strong / weak / trap)は選ぶまで伏せる。"""
    view = choices_view(await _load(ctx, session_id))
    if view is None:
        raise SessionStateError("人間の選択待ちではありません")
    return view


@router.post(
    "/sessions/{session_id}/choices",
    operation_id="chooseOption",
    status_code=status.HTTP_202_ACCEPTED,
    tags=["human"],
    responses={**_ERRORS, 422: {"model": ErrorResponse, "description": "選択肢がない"}},
)
async def choose_option(session_id: str, body: ChooseRequest, ctx: Ctx) -> TaskAccepted:
    """選択肢を選ぶ。代弁者が発言を清書し、次の人間の手番か判決まで進める。"""
    state = await _load(ctx, session_id)
    _ensure_idle(ctx, session_id)
    pending = state.pending_choices
    if pending is None:
        raise SessionStateError("人間の選択待ちではありません")
    if all(o.id != body.option_id for o in pending.options):
        raise InvalidChoiceError(f"選択肢 {body.option_id} はありません")
    return _start_task(ctx, session_id, "choice", _choose(body.option_id))


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
    return [e for e in redact_events(events) if e.seq > after]


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
