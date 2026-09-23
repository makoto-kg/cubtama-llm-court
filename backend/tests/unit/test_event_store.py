from pathlib import Path

import pytest

from llm_court.domain import DebatePhase, PhaseStarted, SessionStarted
from llm_court.engine.store import EventStore, export_jsonl, load_jsonl


def _started() -> SessionStarted:
    return SessionStarted(topic="論題", mode="debate", rounds=1, models={"debater": "m"})


async def test_append_assigns_seq_per_session(tmp_path: Path) -> None:
    store = await EventStore.open(tmp_path / "events.db")
    try:
        a1 = await store.append("a", _started())
        b1 = await store.append("b", _started())
        a2 = await store.append("a", PhaseStarted(phase=DebatePhase.OPENING))
        assert (a1.seq, a2.seq, b1.seq) == (1, 2, 1)
        assert a1.session_id == "a" and b1.session_id == "b"
        assert a2.timestamp >= a1.timestamp

        loaded = await store.load("a")
        assert [e.type for e in loaded] == ["session_started", "phase_started"]
        assert loaded == [a1, a2]
        assert await store.list_sessions() == ["a", "b"]
    finally:
        await store.aclose()


async def test_events_persist_across_connections(tmp_path: Path) -> None:
    path = tmp_path / "events.db"
    store = await EventStore.open(path)
    await store.append("a", _started())
    await store.aclose()

    reopened = await EventStore.open(path)
    try:
        await reopened.append("a", PhaseStarted(phase=DebatePhase.OPENING))
        assert [e.seq for e in await reopened.load("a")] == [1, 2]
    finally:
        await reopened.aclose()


async def test_store_has_no_mutation_api() -> None:
    store = await EventStore.open(None)
    try:
        for name in ("update", "delete", "remove", "replace"):
            assert not hasattr(store, name)
    finally:
        await store.aclose()


async def test_jsonl_roundtrip(tmp_path: Path) -> None:
    store = await EventStore.open(None)
    try:
        await store.append("a", _started())
        await store.append("a", PhaseStarted(phase=DebatePhase.REBUTTAL, round=2))
        events = await store.load("a")
    finally:
        await store.aclose()
    path = tmp_path / "out" / "a.jsonl"
    export_jsonl(events, path)
    assert load_jsonl(path) == events


@pytest.mark.parametrize("empty", ["", "\n"])
def test_load_jsonl_skips_blank_lines(tmp_path: Path, empty: str) -> None:
    path = tmp_path / "e.jsonl"
    path.write_text(empty, encoding="utf-8")
    assert load_jsonl(path) == []
