"""FastAPI アプリの組み立て。"""

from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from llm_court import __version__
from llm_court.api.context import ApiContext
from llm_court.api.hub import SessionHub
from llm_court.api.routes import router
from llm_court.api.tasks import TaskConflictError, TaskRunner
from llm_court.config import Settings
from llm_court.engine.debate import SessionNotFoundError, SessionStateError
from llm_court.engine.recorder import BufferedRecorder
from llm_court.engine.store import EventStore
from llm_court.llm import LLMClient, PromptLoader
from llm_court.llm.backend import OpenAIChatBackend
from llm_court.llm.client import BackendFactory
from llm_court.modes import DEBATE_MODE
from llm_court.research.cache import PageCache
from llm_court.research.fetch import PageFetcher
from llm_court.research.pipeline import ResearchPipeline
from llm_court.research.search import SearXNGClient


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

    @app.exception_handler(TaskConflictError)
    async def _task_conflict(request: Request, exc: TaskConflictError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    app.include_router(router)
    return app
