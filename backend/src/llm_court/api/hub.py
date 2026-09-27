"""セッションごとの SSE 購読者への配信。"""

import asyncio
from collections import defaultdict
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

StreamEventType = Literal["debate", "turn", "witness", "token", "progress", "task"]


class StreamMessage(BaseModel):
    """SSE で送るメッセージ。`debate` は永続イベントで、`id` にその seq を入れる。"""

    model_config = ConfigDict(frozen=True)

    event: StreamEventType
    data: dict[str, Any]
    id: int | None = None


class SessionHub:
    def __init__(self) -> None:
        self._subscribers: defaultdict[str, set[asyncio.Queue[StreamMessage]]] = defaultdict(set)

    def publish(self, session_id: str, message: StreamMessage) -> None:
        for queue in self._subscribers.get(session_id, ()):
            queue.put_nowait(message)

    @contextmanager
    def subscribe(self, session_id: str) -> Generator[asyncio.Queue[StreamMessage]]:
        queue: asyncio.Queue[StreamMessage] = asyncio.Queue()
        self._subscribers[session_id].add(queue)
        try:
            yield queue
        finally:
            self._subscribers[session_id].discard(queue)
            if not self._subscribers[session_id]:
                del self._subscribers[session_id]

    def subscriber_count(self, session_id: str) -> int:
        return len(self._subscribers.get(session_id, ()))
