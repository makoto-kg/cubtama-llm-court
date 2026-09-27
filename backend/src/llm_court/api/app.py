"""FastAPI アプリの組み立て。"""

from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from llm_court import __version__
from llm_court.api.context import ApiContext
from llm_court.api.hub import SessionHub
from llm_court.api.routes import router
from llm_court.api.tasks import TaskConflictError, TaskRunner
from llm_court.api.trial_routes import router as trial_router
from llm_court.config import Settings
from llm_court.engine.debate import (
    InvalidChoiceError,
    SessionNotFoundError,
    SessionStateError,
)
from llm_court.engine.recorder import BufferedRecorder
from llm_court.engine.store import EventStore
from llm_court.llm import LLMClient, PromptLoader
from llm_court.llm.backend import OpenAIChatBackend
from llm_court.llm.client import BackendFactory
from llm_court.modes import DEBATE_MODE, TRIAL_MODE
from llm_court.offline.models import OfflineIndex, OfflinePack
from llm_court.research.cache import PageCache
from llm_court.research.fetch import PageFetcher
from llm_court.research.pipeline import ResearchPipeline
from llm_court.research.search import SearXNGClient
from llm_court.scenario.store import CaseNotFoundError, CaseStore


def create_app(
    settings: Settings | None = None,
    *,
    backend_factory: BackendFactory = OpenAIChatBackend.from_provider,
    http_client_factory: Callable[[], httpx.AsyncClient] = httpx.AsyncClient,
) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        store = await EventStore.open(settings.database_path)
        recorder = BufferedRecorder()
        llm = LLMClient.from_settings(settings, backend_factory=backend_factory, recorder=recorder)
        http = http_client_factory()
        prompts = PromptLoader(settings.prompts_dir)
        research_settings = settings.research
        pipeline = ResearchPipeline(
            llm,
            prompts,
            SearXNGClient(
                settings.searxng_url, timeout_s=research_settings.fetch_timeout_s, client=http
            ),
            PageFetcher(
                research_settings, client=http, cache=PageCache(research_settings.cache_dir)
            ),
            research_settings,
        )
        hub = SessionHub()
        tasks = TaskRunner(hub)
        app.state.ctx = ApiContext(
            settings=settings,
            store=store,
            llm=llm,
            recorder=recorder,
            prompts=prompts,
            mode=DEBATE_MODE,
            research=pipeline,
            hub=hub,
            tasks=tasks,
            trial_mode=TRIAL_MODE,
            cases=CaseStore(settings.scenario.case_dir),
        )
        try:
            yield
        finally:
            await tasks.shutdown()
            await llm.aclose()
            await http.aclose()
            await store.aclose()

    app = FastAPI(
        title="llm-court API",
        version=__version__,
        description="LLM 法廷バトルゲームのバックエンド API(REST + SSE)。",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.api_cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(SessionNotFoundError)
    async def _not_found(request: Request, exc: SessionNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": f"セッション {exc} がありません"})

    @app.exception_handler(SessionStateError)
    async def _state_error(request: Request, exc: SessionStateError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(InvalidChoiceError)
    async def _invalid_choice(request: Request, exc: InvalidChoiceError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(TaskConflictError)
    async def _task_conflict(request: Request, exc: TaskConflictError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(CaseNotFoundError)
    async def _case_not_found(request: Request, exc: CaseNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": f"事件 {exc} がありません"})

    app.include_router(router)
    app.include_router(trial_router)
    _add_offline_schemas(app)
    return app


def _add_offline_schemas(app: FastAPI) -> None:
    """API では使わないオフラインパックの型も OpenAPI に載せる(フロントエンドの型生成用)。"""
    from fastapi.openapi.utils import get_openapi

    def openapi() -> dict[str, Any]:
        if app.openapi_schema is not None:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )
        components: dict[str, Any] = schema.setdefault("components", {}).setdefault("schemas", {})
        for model in (OfflinePack, OfflineIndex):
            extra = model.model_json_schema(
                ref_template="#/components/schemas/{model}", mode="serialization"
            )
            for name, definition in extra.pop("$defs", {}).items():
                components.setdefault(name, definition)
            components.setdefault(model.__name__, extra)
        app.openapi_schema = schema
        return schema

    app.openapi = openapi  # type: ignore[method-assign]
