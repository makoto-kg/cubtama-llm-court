import asyncio
import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from llm_court.api import create_app
from llm_court.api.context import ApiContext
from llm_court.api.sse import session_stream
from llm_court.config import ResearchSettings, Settings
from llm_court.domain import ResearchReport
from llm_court.llm import ChatRequest
from tests.debate_fakes import DebateResponder
from tests.fakes import FakeChatBackend, FakeResponse

BACKEND_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class Api:
    app: FastAPI
    client: httpx.AsyncClient
    fake: FakeChatBackend

    @property
    def ctx(self) -> ApiContext:
        ctx: ApiContext = self.app.state.ctx
        return ctx

    async def wait(self, session_id: str) -> None:
        await self.ctx.tasks.wait(session_id)


def make_settings(tmp_path: Path) -> Settings:
    samples = tmp_path / "samples"
    samples.mkdir(exist_ok=True)
    return Settings(
        sample_evidence_dir=samples,
        database_path=tmp_path / "db.sqlite",
        prompts_dir=BACKEND_ROOT / "prompts",
        models_config_path=BACKEND_ROOT / "config/models.yaml",
        api_sse_keepalive_s=0.05,
        research=ResearchSettings(cache_dir=tmp_path / "cache"),
    )


async def open_api(
    tmp_path: Path, responder: Callable[[ChatRequest], FakeResponse] | None = None
) -> tuple[Api, Any]:
    fake = FakeChatBackend(responder=responder or DebateResponder())
    app = create_app(make_settings(tmp_path), backend_factory=lambda _p: fake)
    lifespan = app.router.lifespan_context(app)
    await lifespan.__aenter__()
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    return Api(app=app, client=client, fake=fake), lifespan


@pytest.fixture
async def api(tmp_path: Path) -> AsyncIterator[Api]:
    api, lifespan = await open_api(tmp_path)
    try:
        yield api
    finally:
        await api.client.aclose()
        await lifespan.__aexit__(None, None, None)


async def create(api: Api, rounds: int = 1) -> str:
    response = await api.client.post("/api/sessions", json={"topic": "論題", "rounds": rounds})
    assert response.status_code == 201, response.text
    return response.json()["session_id"]


async def put_evidence(api: Api, session_id: str, report: ResearchReport) -> dict[str, Any]:
    response = await api.client.put(
        f"/api/sessions/{session_id}/evidence",
        content=report.model_dump_json(),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 200, response.text
    return response.json()


def parse_sse(body: str) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for block in body.split("\n\n"):
        fields: dict[str, Any] = {}
        for line in block.splitlines():
            if line.startswith(":"):
                continue
            key, _, value = line.partition(": ")
            fields[key] = value
        if "event" in fields:
            fields["data"] = json.loads(fields["data"])
            messages.append(fields)
    return messages


async def test_step_by_step_until_verdict(api: Api, research_report: ResearchReport) -> None:
    session_id = await create(api)
    view = (await api.client.get(f"/api/sessions/{session_id}")).json()
    assert view["status"] == "awaiting_evidence"
    assert view["next_turn"] is None

    response = await api.client.post(f"/api/sessions/{session_id}/advance")
    assert response.status_code == 409
    assert "証拠品" in response.json()["detail"]

    view = await put_evidence(api, session_id, research_report)
    assert view["status"] == "ready"
    assert view["next_turn"] == {
        "kind": "statement",
        "phase": "opening",
        "round": 0,
        "side": "affirmative",
        "by_human": False,
    }
    response = await api.client.put(
        f"/api/sessions/{session_id}/evidence",
        content=research_report.model_dump_json(),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 409

    turns: list[dict[str, Any]] = []
    for _ in range(7):  # 発言 6 + 判決
        response = await api.client.post(f"/api/sessions/{session_id}/advance")
        assert response.status_code == 202, response.text
        assert response.json()["task"]["kind"] == "advance"
        await api.wait(session_id)
        view = (await api.client.get(f"/api/sessions/{session_id}")).json()
        turns.append(view["next_turn"])

    assert [t["phase"] if t else None for t in turns] == [
        "opening",
        "rebuttal",
        "rebuttal",
        "closing",
        "closing",
        "verdict",
        None,
    ]
    assert view["status"] == "finished"
    assert view["verdict"]["winner"] == "affirmative"
    assert len(view["statements"]) == 6
    assert view["running_task"] is None

    response = await api.client.post(f"/api/sessions/{session_id}/advance")
    assert response.status_code == 409
    assert "閉廷" in response.json()["detail"]

    record = await api.client.get(f"/api/sessions/{session_id}/record")
    assert record.headers["content-type"].startswith("text/markdown")
    assert record.text.startswith("# 法廷記録: 論題")

    summary = (await api.client.get(f"/api/sessions/{session_id}/summary")).json()
    assert summary["llm_calls"] == 14
    assert len(summary["turns"]) == 6

    events = (await api.client.get(f"/api/sessions/{session_id}/events")).json()
    assert events[0]["type"] == "session_started"
    assert events[-1]["type"] == "verdict_delivered"
    later = (await api.client.get(f"/api/sessions/{session_id}/events?after=3")).json()
    assert [e["seq"] for e in later] == [e["seq"] for e in events if e["seq"] > 3]

    sessions = (await api.client.get("/api/sessions")).json()
    assert [(s["session_id"], s["status"]) for s in sessions] == [(session_id, "finished")]


async def test_run_with_sse(api: Api, research_report: ResearchReport) -> None:
    session_id = await create(api)
    await put_evidence(api, session_id, research_report)

    stream = asyncio.create_task(api.client.get(f"/api/sessions/{session_id}/stream"))
    for _ in range(100):  # 購読が始まるのを待つ
        if api.ctx.hub.subscriber_count(session_id):
            break
        await asyncio.sleep(0.01)
    response = await api.client.post(f"/api/sessions/{session_id}/run")
    assert response.status_code == 202
    body = (await asyncio.wait_for(stream, timeout=10)).text
    messages = parse_sse(body)

    kinds = [m["event"] for m in messages]
    assert kinds[0] == "debate"  # 履歴(開廷・証拠品)から始まる
    assert {"turn", "token", "task"} <= set(kinds)
    debate = [m for m in messages if m["event"] == "debate"]
    seqs = [int(m["id"]) for m in debate]
    assert seqs == sorted(seqs) and len(seqs) == len(set(seqs))
    assert debate[-1]["data"]["type"] == "verdict_delivered"
    assert messages[-1] == debate[-1]  # 判決で閉じる

    first_turn = next(m for m in messages if m["event"] == "turn")["data"]
    assert first_turn == {"phase": "opening", "round": 0, "side": "affirmative"}
    tokens = "".join(
        m["data"]["text"]
        for m in messages
        if m["event"] == "token"
        and m["data"]["phase"] == "opening"
        and m["data"]["side"] == "affirmative"
    )
    statements = [m["data"]["statement"] for m in debate if m["data"]["type"] == "statement_made"]
    assert tokens == statements[0]["text"]
    assert any(m["data"] == {"kind": "run", "status": "started"} for m in messages)


async def test_sse_replay_after_finish(api: Api, research_report: ResearchReport) -> None:
    session_id = await create(api)
    await put_evidence(api, session_id, research_report)
    await api.client.post(f"/api/sessions/{session_id}/run")
    await api.wait(session_id)
    events = (await api.client.get(f"/api/sessions/{session_id}/events")).json()

    # Last-Event-ID 以降だけが再送され、判決で閉じる
    response = await api.client.get(
        f"/api/sessions/{session_id}/stream", headers={"Last-Event-ID": "5"}
    )
    replay = parse_sse(response.text)
    assert [int(m["id"]) for m in replay] == [e["seq"] for e in events if e["seq"] > 5]

    # すべて受信済みなら何も送らずに閉じる
    last = events[-1]["seq"]
    response = await api.client.get(f"/api/sessions/{session_id}/stream?after={last}")
    assert parse_sse(response.text) == []


async def test_not_found(api: Api) -> None:
    for method, path in [
        ("GET", "/api/sessions/nope"),
        ("POST", "/api/sessions/nope/advance"),
        ("POST", "/api/sessions/nope/run"),
        ("POST", "/api/sessions/nope/research"),
        ("GET", "/api/sessions/nope/stream"),
        ("GET", "/api/sessions/nope/events"),
        ("GET", "/api/sessions/nope/record"),
        ("GET", "/api/sessions/nope/summary"),
    ]:
        response = await api.client.request(method, path)
        assert response.status_code == 404, (method, path)


async def test_validation_error(api: Api) -> None:
    response = await api.client.post("/api/sessions", json={"topic": "", "rounds": 0})
    assert response.status_code == 422


async def test_task_conflict(tmp_path: Path, research_report: ResearchReport) -> None:
    responder = DebateResponder()

    def slow(request: ChatRequest) -> FakeResponse:
        response = responder(request)
        return response.model_copy(update={"delay_s": 0.05})

    api, lifespan = await open_api(tmp_path, slow)
    try:
        session_id = await create(api)
        await put_evidence(api, session_id, research_report)
        assert (await api.client.post(f"/api/sessions/{session_id}/run")).status_code == 202
        view = (await api.client.get(f"/api/sessions/{session_id}")).json()
        assert view["running_task"]["kind"] == "run"
        for path in ("advance", "run", "research"):
            response = await api.client.post(f"/api/sessions/{session_id}/{path}")
            assert response.status_code == 409, path
        await api.wait(session_id)
        view = (await api.client.get(f"/api/sessions/{session_id}")).json()
        assert view["status"] == "finished"
    finally:
        await api.client.aclose()
        await lifespan.__aexit__(None, None, None)


async def test_parallel_sessions_keep_llm_calls_separate(
    api: Api, research_report: ResearchReport
) -> None:
    ids = [await create(api), await create(api)]
    for session_id in ids:
        await put_evidence(api, session_id, research_report)
    for session_id in ids:
        assert (await api.client.post(f"/api/sessions/{session_id}/run")).status_code == 202
    await asyncio.gather(*(api.wait(i) for i in ids))

    call_ids: list[set[str]] = []
    for session_id in ids:
        events = (await api.client.get(f"/api/sessions/{session_id}/events")).json()
        calls = [e["call"]["call_id"] for e in events if e["type"] == "llm_call_recorded"]
        assert len(calls) == 14
        call_ids.append(set(calls))
    assert not call_ids[0] & call_ids[1]


async def test_research_task(api: Api, research_report: ResearchReport) -> None:
    progress: list[str] = []

    class StubResearch:
        async def run(
            self, topic: str, on_progress: Callable[[str], None] | None = None
        ) -> ResearchReport:
            if on_progress:
                on_progress("検索中")
            progress.append(topic)
            return research_report

    api.ctx.research = StubResearch()
    session_id = await create(api)
    response = await api.client.post(f"/api/sessions/{session_id}/research")
    assert response.status_code == 202
    await api.wait(session_id)
    assert progress == ["論題"]
    view = (await api.client.get(f"/api/sessions/{session_id}")).json()
    assert view["status"] == "ready"
    assert len(view["evidence"]) == 2
    response = await api.client.post(f"/api/sessions/{session_id}/research")
    assert response.status_code == 409


async def test_state_is_rebuilt_after_restart(
    tmp_path: Path, research_report: ResearchReport
) -> None:
    api, lifespan = await open_api(tmp_path)
    try:
        session_id = await create(api)
        await put_evidence(api, session_id, research_report)
        await api.client.post(f"/api/sessions/{session_id}/advance")
        await api.wait(session_id)
        before = (await api.client.get(f"/api/sessions/{session_id}")).json()
    finally:
        await api.client.aclose()
        await lifespan.__aexit__(None, None, None)

    # 同じ DB で起動し直す
    api, lifespan = await open_api(tmp_path)
    try:
        after = (await api.client.get(f"/api/sessions/{session_id}")).json()
        assert after == before
        assert after["next_turn"]["side"] == "negative"
        await api.client.post(f"/api/sessions/{session_id}/run")
        await api.wait(session_id)
        final = (await api.client.get(f"/api/sessions/{session_id}")).json()
        assert final["status"] == "finished"
    finally:
        await api.client.aclose()
        await lifespan.__aexit__(None, None, None)


async def test_failed_task_aborts_session(tmp_path: Path, research_report: ResearchReport) -> None:
    api, lifespan = await open_api(tmp_path, lambda _r: FakeResponse.text(""))
    try:
        session_id = await create(api)
        await put_evidence(api, session_id, research_report)
        await api.client.post(f"/api/sessions/{session_id}/advance")
        await api.wait(session_id)
        view = (await api.client.get(f"/api/sessions/{session_id}")).json()
        assert view["status"] == "aborted"
        assert "発言が空" in view["aborted"]
    finally:
        await api.client.aclose()
        await lifespan.__aexit__(None, None, None)


def test_openapi_schema() -> None:
    schema = create_app().openapi()
    operations = {op["operationId"] for path in schema["paths"].values() for op in path.values()}
    assert {"createSession", "advanceSession", "runSession", "streamSession", "setEvidence"} <= (
        operations
    )
    stream = schema["paths"]["/api/sessions/{session_id}/stream"]["get"]
    assert "text/event-stream" in stream["responses"]["200"]["content"]
    events = schema["paths"]["/api/sessions/{session_id}/events"]["get"]
    items = events["responses"]["200"]["content"]["application/json"]["schema"]["items"]
    assert items["discriminator"]["propertyName"] == "type"


# --- 人間 vs LLM ---


async def create_human(api: Api, side: str = "negative") -> str:
    response = await api.client.post(
        "/api/sessions", json={"topic": "論題", "rounds": 1, "human_side": side}
    )
    assert response.status_code == 201, response.text
    return response.json()["session_id"]


async def test_human_game_via_api(api: Api, research_report: ResearchReport) -> None:
    session_id = await create_human(api)
    await put_evidence(api, session_id, research_report)
    response = await api.client.get(f"/api/sessions/{session_id}/choices")
    assert response.status_code == 409  # まだ選択待ちではない

    assert (await api.client.post(f"/api/sessions/{session_id}/run")).status_code == 202
    await api.wait(session_id)

    moves = 0
    while True:
        view = (await api.client.get(f"/api/sessions/{session_id}")).json()
        if view["status"] == "finished":
            break
        assert view["next_turn"]["by_human"] is True
        choices = (await api.client.get(f"/api/sessions/{session_id}/choices")).json()
        assert choices == view["pending_choices"]
        # 強さ・判断理由・由来は伏せてある
        for option in choices["options"]:
            assert option["source"] is None
            if option["contradiction"]:
                assert option["contradiction"]["strength"] is None
                assert option["contradiction"]["rationale"] is None
        # イベント一覧でも伏せてある
        events = (await api.client.get(f"/api/sessions/{session_id}/events")).json()
        prepared = [e for e in events if e["type"] == "choices_prepared"][-1]
        assert all(o["source"] is None for o in prepared["options"])

        response = await api.client.post(
            f"/api/sessions/{session_id}/choices", json={"option_id": "nope"}
        )
        assert response.status_code == 422
        option = choices["options"][-1]  # 反論では「ゆさぶる」(減点なし)
        response = await api.client.post(
            f"/api/sessions/{session_id}/choices", json={"option_id": option["id"]}
        )
        assert response.status_code == 202, response.text
        assert response.json()["task"]["kind"] == "choice"
        await api.wait(session_id)
        moves += 1

    assert moves == 3
    assert view["verdict"]["decided_by"] == "judge"
    assert view["penalty_gauge"] == 5
    assert [c["kind"] for c in view["choices"]] == ["argument", "probe", "argument"]
    assert view["choices"][0]["source"] == "analyst"  # 選んだ後は公開

    # 選択済みの選択肢は、イベント一覧でも公開される
    events = (await api.client.get(f"/api/sessions/{session_id}/events")).json()
    rebuttal = [e for e in events if e["type"] == "choices_prepared"][1]
    assert {o["contradiction"]["strength"] for o in rebuttal["options"] if o["contradiction"]} == {
        "strong",
        "weak",
        "trap",
    }


async def test_sse_redacts_pending_choices(api: Api, research_report: ResearchReport) -> None:
    session_id = await create_human(api)
    await put_evidence(api, session_id, research_report)
    await api.client.post(f"/api/sessions/{session_id}/run")
    await api.wait(session_id)
    await api.client.post(
        f"/api/sessions/{session_id}/choices",
        json={
            "option_id": (await api.client.get(f"/api/sessions/{session_id}/choices")).json()[
                "options"
            ][0]["id"]
        },
    )
    await api.wait(session_id)  # 反論の選択待ち

    # 選択待ちのまま SSE を開くと、履歴の選択肢は伏せられている。判決まで閉じないため、
    # ジェネレーターを直接読み、履歴の分だけ取り出す
    history = len(await api.ctx.store.load(session_id))
    stream = session_stream(
        session_id=session_id,
        after=0,
        store=api.ctx.store,
        hub=api.ctx.hub,
        keepalive_s=api.ctx.settings.api_sse_keepalive_s,
    )
    chunks = [await anext(stream) for _ in range(history)]
    await stream.aclose()
    prepared = [
        m["data"]
        for m in parse_sse("".join(chunks))
        if m["event"] == "debate" and m["data"]["type"] == "choices_prepared"
    ]
    assert prepared[0]["options"][0]["source"] == "analyst"  # 選択済み(冒頭陳述)
    assert all(o["source"] is None for o in prepared[-1]["options"])  # 未選択(反論)


async def test_llm_session_has_no_choices(api: Api, research_report: ResearchReport) -> None:
    session_id = await create(api)
    await put_evidence(api, session_id, research_report)
    response = await api.client.post(
        f"/api/sessions/{session_id}/choices", json={"option_id": "T01-1"}
    )
    assert response.status_code == 409


# --- 同梱の証拠品・設定・思考ログ ---


async def test_evidence_samples(api: Api, research_report: ResearchReport) -> None:
    samples = api.ctx.settings.sample_evidence_dir
    (samples / "basic-income.json").write_text(research_report.model_dump_json(), encoding="utf-8")
    (samples / "notes.txt").write_text("対象外", encoding="utf-8")

    items = (await api.client.get("/api/evidence-samples")).json()
    assert [(i["name"], i["topic"], i["evidence_count"]) for i in items] == [
        ("basic-income", research_report.topic, 2)
    ]

    session_id = await create(api)
    response = await api.client.post(f"/api/sessions/{session_id}/evidence/samples/nope")
    assert response.status_code == 404
    response = await api.client.post(f"/api/sessions/{session_id}/evidence/samples/..%2Fdb")
    assert response.status_code == 404
    response = await api.client.post(f"/api/sessions/{session_id}/evidence/samples/basic-income")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "ready"
    assert len(response.json()["evidence"]) == 2


async def test_config(api: Api) -> None:
    config = (await api.client.get("/api/config")).json()
    roles = {r["role"]: r for r in config["roles"]}
    assert set(roles) >= {"debater", "judge", "analyst", "advocate"}
    assert roles["debater"]["base_url"] == "http://localhost:1234/v1"
    assert "api_key" not in json.dumps(config)


async def test_thinking_log_hides_pending_analyst_output(
    api: Api, research_report: ResearchReport
) -> None:
    session_id = await create_human(api)
    await put_evidence(api, session_id, research_report)
    await api.client.post(f"/api/sessions/{session_id}/run")
    await api.wait(session_id)

    def analyst_calls(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            e["call"]
            for e in events
            if e["type"] == "llm_call_recorded" and e["call"]["role"] == "analyst"
        ]

    events = (await api.client.get(f"/api/sessions/{session_id}/events")).json()
    debater = next(e["call"] for e in events if e["type"] == "llm_call_recorded")
    assert debater["messages"] and debater["response_text"]  # 入出力が記録されている
    (pending,) = analyst_calls(events)
    assert pending["messages"]  # 入力は見せる
    assert pending["response_text"] is None and pending["parsed"] is None  # 出力は伏せる

    option = (await api.client.get(f"/api/sessions/{session_id}/choices")).json()["options"][0]
    await api.client.post(f"/api/sessions/{session_id}/choices", json={"option_id": option["id"]})
    await api.wait(session_id)
    events = (await api.client.get(f"/api/sessions/{session_id}/events")).json()
    calls = analyst_calls(events)
    assert calls[0]["parsed"] is not None  # 選択後は公開
    assert calls[-1]["parsed"] is None  # 次の手番の分は伏せたまま
