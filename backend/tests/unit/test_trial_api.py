from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from llm_court.api import create_app
from llm_court.api.sse import session_stream
from llm_court.config import ScenarioSettings
from llm_court.domain import Case, ResearchReport, TrialChoicesPrepared
from llm_court.llm import PromptLoader
from llm_court.scenario.store import CaseStore
from tests.fakes import FakeChatBackend
from tests.trial_fakes import COLLAPSE_TEXT, TrialResponder, make_case
from tests.unit.test_api import Api, make_settings, parse_sse


@pytest.fixture
async def case(prompts: PromptLoader, research_report: ResearchReport) -> Case:
    return await make_case(prompts, research_report)


@pytest.fixture
async def api(tmp_path: Path, case: Case) -> AsyncIterator[Api]:
    case_dir = tmp_path / "cases"
    store = CaseStore(case_dir)
    store.save(case)
    unsolved = case.model_copy(
        update={
            "id": "unsolved1",
            "validation": case.validation.model_copy(update={"solved": False})
            if case.validation
            else None,
        }
    )
    store.save(unsolved)
    settings = make_settings(tmp_path).model_copy(
        update={"scenario": ScenarioSettings(case_dir=case_dir)}
    )
    fake = FakeChatBackend(responder=TrialResponder())
    app = create_app(settings, backend_factory=lambda _p: fake)
    lifespan = app.router.lifespan_context(app)
    await lifespan.__aenter__()
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    try:
        yield Api(app=app, client=client, fake=fake)
    finally:
        await client.aclose()
        await lifespan.__aexit__(None, None, None)


async def start(api: Api, case: Case) -> dict[str, Any]:
    response = await api.client.post("/api/trials", json={"case_id": case.id})
    assert response.status_code == 201, response.text
    return response.json()


async def pick(api: Api, session_id: str, strength: str | None, kind: str = "present") -> str:
    """ストア上の(伏せていない)選択肢から、指定した強さの選択肢を探す(テスト用)。"""
    prepared = [
        e for e in await api.ctx.store.load(session_id) if isinstance(e, TrialChoicesPrepared)
    ][-1]
    return next(o.id for o in prepared.options if o.kind == kind and o.strength == strength)


async def choose(api: Api, session_id: str, option: str) -> dict[str, Any]:
    response = await api.client.post(
        f"/api/trials/{session_id}/choices", json={"option_id": option}
    )
    assert response.status_code == 202, response.text
    await api.wait(session_id)
    return (await api.client.get(f"/api/trials/{session_id}")).json()


async def test_list_cases(api: Api, case: Case) -> None:
    cases = (await api.client.get("/api/cases")).json()
    assert [c["id"] for c in cases] == [case.id]
    assert cases[0]["contradictions"] == 2 and cases[0]["solvable"]
    assert "hidden_truth" not in cases[0]
    all_cases = (await api.client.get("/api/cases", params={"all": "true"})).json()
    assert {c["id"] for c in all_cases} == {case.id, "unsolved1"}


async def test_full_trial_over_api(api: Api, case: Case) -> None:
    view = await start(api, case)
    session_id = view["session_id"]
    assert view["status"] == "in_progress" and view["stage"] == "choosing"
    assert view["testimony_id"] == case.testimonies[0].id
    assert "hidden_truth" not in view["case"] and "contradictions" not in view["case"]
    assert all(o["strength"] is None for o in view["pending_options"])
    assert all(o["contradiction_id"] is None for o in view["pending_options"])
    assert view["explanation"] is None

    view = await choose(api, session_id, await pick(api, session_id, "trap"))
    exchange = view["exchanges"][-1]
    assert exchange["option"]["strength"] == "trap" and exchange["penalty"] == 2
    assert exchange["check"] is None  # 閉廷前は伏せる
    assert view["penalty_gauge"] == view["penalty_gauge_max"] - 2

    view = await choose(api, session_id, await pick(api, session_id, "strong"))
    assert view["exchanges"][-1]["text"] == COLLAPSE_TEXT
    assert view["solved_line_ids"] == ["TS-01-2"]
    view = await choose(api, session_id, await pick(api, session_id, "strong"))
    assert view["stage"] == "answering" and view["status"] == "answering"
    assert view["pending_options"] == []

    # 閉廷前のイベントログは非公開の情報を伏せる
    events = (await api.client.get(f"/api/sessions/{session_id}/events")).json()
    started = events[0]
    assert started["type"] == "trial_started"
    assert started["case"]["contradictions"] == [] and started["case"]["witness_scripts"] == []
    assert started["case"]["question"]["answer_index"] == -1
    calls = [e["call"] for e in events if e["type"] == "llm_call_recorded"]
    assert calls and all(c["messages"] is None and c["response_text"] is None for c in calls)
    assert all(
        o["strength"] is None
        for e in events
        if e["type"] == "trial_choices_prepared"
        for o in e["options"]
    )

    response = await api.client.post(f"/api/trials/{session_id}/answer", json={"index": 99})
    assert response.status_code == 422
    response = await api.client.post(
        f"/api/trials/{session_id}/answer", json={"index": case.question.answer_index}
    )
    assert response.status_code == 200, response.text
    view = response.json()
    assert view["status"] == "finished" and view["result"] == "solved"
    assert view["answer_correct"] is True
    explanation = view["explanation"]
    assert [i["contradiction_id"] for i in explanation["items"]] == ["X-01", "X-02"]
    assert explanation["learning_points"][0]["sources"]
    assert view["exchanges"][0]["check"] is not None  # 閉廷後は公開

    # 閉廷後はすべて公開
    events = (await api.client.get(f"/api/sessions/{session_id}/events")).json()
    assert events[0]["case"]["contradictions"]

    response = await api.client.post(
        f"/api/trials/{session_id}/objections",
        json={"target_kind": "trap", "target_id": "X-01/CE-03", "comment": "罠が不自然"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["objections"][0]["target_id"] == "X-01/CE-03"
    response = await api.client.post(
        f"/api/trials/{session_id}/objections",
        json={"target_kind": "learning_point", "target_id": "LP-99", "comment": "x"},
    )
    assert response.status_code == 422
    response = await api.client.post(
        f"/api/trials/{session_id}/objections",
        json={"target_kind": "learning_point", "target_id": "LP-01", "comment": "  "},
    )
    assert response.status_code == 422

    # SSE は閉廷で終わる
    response = await api.client.get(f"/api/sessions/{session_id}/stream")
    messages = parse_sse(response.text)
    assert messages[-1]["data"]["type"] == "trial_finished"


async def test_trial_errors(api: Api, case: Case) -> None:
    assert (await api.client.post("/api/trials", json={"case_id": "nothing"})).status_code == 404
    assert (await api.client.post("/api/trials", json={"case_id": "../x"})).status_code == 404
    assert (await api.client.get("/api/trials/nothing")).status_code == 404

    session_id = (await start(api, case))["session_id"]
    response = await api.client.post(
        f"/api/trials/{session_id}/choices", json={"option_id": "Q99-1"}
    )
    assert response.status_code == 422
    assert (
        await api.client.post(f"/api/trials/{session_id}/answer", json={"index": 0})
    ).status_code == 409
    assert (await api.client.post(f"/api/trials/{session_id}/advance")).status_code == 409
    response = await api.client.post(
        f"/api/trials/{session_id}/objections",
        json={"target_kind": "learning_point", "target_id": "LP-01", "comment": "早い"},
    )
    assert response.status_code == 409

    # 裁判のセッションはディベートの一覧・操作の対象にしない
    assert (await api.client.get("/api/sessions")).json() == []
    assert (await api.client.get(f"/api/sessions/{session_id}")).status_code == 404
    assert (await api.client.get(f"/api/sessions/{session_id}/summary")).status_code == 404


async def test_sse_streams_witness_tokens(api: Api, case: Case) -> None:
    session_id = (await start(api, case))["session_id"]
    history = len(await api.ctx.store.load(session_id))
    stream = session_stream(
        session_id=session_id,
        after=0,
        store=api.ctx.store,
        hub=api.ctx.hub,
        keepalive_s=api.ctx.settings.api_sse_keepalive_s,
    )
    chunks = [await anext(stream) for _ in range(history)]
    started = parse_sse("".join(chunks))[0]["data"]
    assert started["case"]["witness_scripts"] == []

    await api.client.post(
        f"/api/trials/{session_id}/choices",
        json={"option_id": await pick(api, session_id, "strong")},
    )
    live: list[str] = []
    while True:
        chunk = await anext(stream)
        if chunk.startswith(":"):
            continue
        live.append(chunk)
        messages = parse_sse("".join(live))
        if (
            messages
            and messages[-1]["event"] == "debate"
            and messages[-1]["data"]["type"]
            in (
                "trial_choices_prepared",
                "testimony_started",
            )
        ):
            break
    await stream.aclose()
    await api.wait(session_id)
    events = [m["event"] for m in messages]
    assert "witness" in events and "token" in events
    llm_calls = [
        m["data"]["call"]
        for m in messages
        if m["event"] == "debate" and m["data"]["type"] == "llm_call_recorded"
    ]
    assert llm_calls and all(c["messages"] is None for c in llm_calls)
