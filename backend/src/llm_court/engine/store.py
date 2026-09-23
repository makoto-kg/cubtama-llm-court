"""SQLite による追記専用のイベントストア。

更新・削除の API は持たない。`seq` はセッション内の連番でストアが採番する。
"""

import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import (
    Column,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
    insert,
    select,
)
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from llm_court.domain import EVENT_ADAPTER, Event

_metadata = MetaData()
events_table = Table(
    "events",
    _metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("session_id", String(64), nullable=False, index=True),
    Column("seq", Integer, nullable=False),
    Column("type", String(64), nullable=False),
    Column("timestamp", String(40), nullable=False),
    Column("payload", Text, nullable=False),
    UniqueConstraint("session_id", "seq", name="uq_events_session_seq"),
)


class EventStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self._lock = asyncio.Lock()

    @classmethod
    async def open(cls, path: Path | None) -> "EventStore":
        """SQLite ファイル(None ならインメモリ)を開き、テーブルを用意する。"""
        if path is None:
            url = "sqlite+aiosqlite:///:memory:"
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            url = f"sqlite+aiosqlite:///{path}"
        engine = create_async_engine(url)
        async with engine.begin() as conn:
            await conn.run_sync(_metadata.create_all)
        return cls(engine)

    async def aclose(self) -> None:
        await self._engine.dispose()

    async def append(self, session_id: str, event: Event) -> Event:
        """イベントを追記し、`session_id`・`seq`・`timestamp` を設定したものを返す。"""
        async with self._lock, self._engine.begin() as conn:
            current = await conn.scalar(
                select(func.max(events_table.c.seq)).where(events_table.c.session_id == session_id)
            )
            stored = event.model_copy(
                update={
                    "session_id": session_id,
                    "seq": (current or 0) + 1,
                    "timestamp": datetime.now(UTC),
                }
            )
            await conn.execute(
                insert(events_table).values(
                    session_id=session_id,
                    seq=stored.seq,
                    type=stored.type,
                    timestamp=stored.timestamp.isoformat(),
                    payload=stored.model_dump_json(),
                )
            )
        return stored

    async def load(self, session_id: str) -> list[Event]:
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                select(events_table.c.payload)
                .where(events_table.c.session_id == session_id)
                .order_by(events_table.c.seq)
            )
            return [EVENT_ADAPTER.validate_json(row.payload) for row in rows]

    async def list_sessions(self) -> list[str]:
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                select(events_table.c.session_id)
                .group_by(events_table.c.session_id)
                .order_by(func.min(events_table.c.id))
            )
            return [row.session_id for row in rows]


def export_jsonl(events: Sequence[Event], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for event in events:
            f.write(event.model_dump_json() + "\n")


def load_jsonl(path: Path) -> list[Event]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [EVENT_ADAPTER.validate_json(line) for line in lines if line.strip()]
