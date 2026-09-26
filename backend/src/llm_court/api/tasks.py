"""セッションごとのバックグラウンドタスク(捜査・進行)。1 セッションにつき同時に 1 つまで。"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from llm_court.api.hub import SessionHub, StreamMessage

logger = logging.getLogger(__name__)

TaskKind = Literal["research", "advance", "run"]


class TaskConflictError(Exception):
    """そのセッションではすでにタスクが実行中。"""


class TaskView(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: TaskKind
    started_at: datetime


class TaskRunner:
    def __init__(self, hub: SessionHub) -> None:
        self._hub = hub
        self._tasks: dict[str, tuple[TaskView, asyncio.Task[None]]] = {}

    def running(self, session_id: str) -> TaskView | None:
        entry = self._tasks.get(session_id)
        return entry[0] if entry else None

    def start(
        self, session_id: str, kind: TaskKind, job: Callable[[], Awaitable[None]]
    ) -> TaskView:
        if session_id in self._tasks:
            raise TaskConflictError(f"セッション {session_id} ではタスクが実行中です")
        view = TaskView(kind=kind, started_at=datetime.now(UTC))

        async def wrapper() -> None:
            self._publish(session_id, view, "started")
            try:
                await job()
            except asyncio.CancelledError:
                self._publish(session_id, view, "cancelled")
                raise
            except Exception as e:
                # 失敗はエンジンが SessionAborted として記録済み。ここでは通知だけ行う
                logger.warning("タスクが失敗しました(%s %s): %s", session_id, kind, e)
                self._publish(session_id, view, "failed", f"{type(e).__name__}: {e}")
            else:
                self._publish(session_id, view, "completed")
            finally:
                self._tasks.pop(session_id, None)

        self._tasks[session_id] = (view, asyncio.create_task(wrapper()))
        return view

    def _publish(
        self, session_id: str, view: TaskView, status: str, error: str | None = None
    ) -> None:
        data: dict[str, object] = {"kind": view.kind, "status": status}
        if error is not None:
            data["error"] = error
        self._hub.publish(session_id, StreamMessage(event="task", data=data))

    async def wait(self, session_id: str) -> None:
        """実行中のタスクが終わるまで待つ(テスト用)。"""
        entry = self._tasks.get(session_id)
        if entry is not None:
            await asyncio.gather(entry[1], return_exceptions=True)

    async def shutdown(self) -> None:
        tasks = [task for _, task in self._tasks.values()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
