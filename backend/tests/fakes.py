"""単体テスト用のフェイク LLM バックエンド。実サーバーを呼ばず、録画済み応答を返す。"""

import asyncio
import json
from collections import deque
from collections.abc import AsyncIterator, Callable, Iterable
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from llm_court.llm import (
    ChatChunk,
    ChatRequest,
    LLMConnectionError,
    LLMError,
    LLMRequestRejectedError,
    Usage,
)

FIXTURES = Path(__file__).parent / "fixtures" / "llm"


class FakeError(BaseModel):
    kind: Literal["rejected", "connection", "other"]
    status: int = 400
    message: str = "error"


class FakeResponse(BaseModel):
    chunks: list[ChatChunk] = []
    error: FakeError | None = None
    delay_s: float = 0.0

    @classmethod
    def text(cls, content: str, *, output_tokens: int = 10) -> "FakeResponse":
        return cls(
            chunks=[
                ChatChunk(content=content),
                ChatChunk(usage=Usage(input_tokens=5, output_tokens=output_tokens)),
            ]
        )


class FakeRecording(BaseModel):
    responses: list[FakeResponse]


def load_recording(name: str) -> list[FakeResponse]:
    data = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    return FakeRecording.model_validate(data).responses


class FakeChatBackend:
    """応答を順に返す(または `responder` で都度決める)。受け取ったリクエストを記録する。"""

    def __init__(
        self,
        responses: Iterable[FakeResponse] = (),
        *,
        responder: Callable[[ChatRequest], FakeResponse] | None = None,
    ) -> None:
        self._queue = deque(responses)
        self._responder = responder
        self.requests: list[ChatRequest] = []
        self.active = 0
        self.max_active = 0
        self.closed = False

    def _next(self, request: ChatRequest) -> FakeResponse:
        self.requests.append(request)
        if self._responder is not None:
            return self._responder(request)
        if not self._queue:
            raise AssertionError("フェイク応答が足りません")
        return self._queue.popleft()

    @staticmethod
    def _raise(error: FakeError) -> None:
        if error.kind == "rejected":
            raise LLMRequestRejectedError(error.message, error.status)
        if error.kind == "connection":
            raise LLMConnectionError(error.message)
        raise LLMError(error.message)

    async def stream(self, request: ChatRequest) -> AsyncIterator[ChatChunk]:
        response = self._next(request)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if response.delay_s:
                await asyncio.sleep(response.delay_s)
            if response.error is not None:
                self._raise(response.error)
            for chunk in response.chunks:
                yield chunk
        finally:
            self.active -= 1

    async def complete(self, request: ChatRequest) -> ChatChunk:
        response = self._next(request)
        if response.error is not None:
            self._raise(response.error)
        usage = next((c.usage for c in response.chunks if c.usage), None)
        return ChatChunk(
            content="".join(c.content for c in response.chunks),
            reasoning="".join(c.reasoning for c in response.chunks),
            usage=usage,
        )

    async def aclose(self) -> None:
        self.closed = True
