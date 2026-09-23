import json
from datetime import UTC, date, datetime
from typing import Any

import pytest

from llm_court.config import ResearchSettings
from llm_court.llm import ChatRequest, InMemoryRecorder, LLMClient, PromptLoader
from llm_court.research.cache import FetchedPage
from llm_court.research.fetch import FetchFailure
from llm_court.research.pipeline import ResearchPipeline, interleave
from llm_court.research.search import SearchError, SearchHit
from tests.fakes import FakeChatBackend, FakeError, FakeResponse
from tests.unit.test_llm_client import make_config

TOPIC = "ベーシックインカムを導入すべきか"
BODY = (
    "ある国では2年間、失業者2,000人に毎月一定額を支給する実験を行った。"
    "受給者の生活満足度は改善したが、就業日数に大きな差はなかった。" * 10
)


def page_text(url: str) -> str:
    return f"{url} の本文。{BODY}"


class FakeSearcher:
    def __init__(self, results: dict[str, list[SearchHit] | Exception]) -> None:
        self.results = results
        self.queries: list[str] = []

    async def search(self, query: str, *, limit: int) -> list[SearchHit]:
        self.queries.append(query)
        result = self.results.get(query, [])
        if isinstance(result, Exception):
            raise result
        return result[:limit]


class FakeFetcher:
    def __init__(self, overrides: dict[str, FetchedPage | FetchFailure] | None = None) -> None:
        self.overrides = overrides or {}
        self.urls: list[str] = []

    async def fetch(self, url: str) -> FetchedPage | FetchFailure:
        self.urls.append(url)
        if url in self.overrides:
            return self.overrides[url]
        return FetchedPage(
            url=url,
            title=None,
            text=page_text(url),
            published_date="2025-01-01",
            fetched_at=datetime(2026, 9, 1, tzinfo=UTC),
        )


def hit(n: int, query: str = "q1", title: str | None = None) -> SearchHit:
    return SearchHit(
        url=f"https://site{n}.example/a", title=title or f"記事その{n}の見出し", query=query
    )


def evidence_json(
    url: str, *, relevant: bool = True, quote: str = "失業者2,000人に毎月一定額を支給する実験"
) -> str:
    data: dict[str, Any] = {
        "relevant": relevant,
        "title": f"証拠 {url}",
        "summary": "実験の要約。",
        "key_facts": [
            {"text": "2,000人に給付した", "quote": quote},
            {"text": "捏造された事実", "quote": "就業日数が半分に減った"},
        ],
    }
    return json.dumps(data, ensure_ascii=False)


def responder_for(queries: list[str], per_url: dict[str, str | FakeResponse] | None = None) -> Any:
    per_url = per_url or {}

    def respond(request: ChatRequest) -> FakeResponse:
        user = request.messages[-1].content
        if "検索クエリを" in user:
            return FakeResponse.text(json.dumps({"queries": queries}, ensure_ascii=False))
        url = next(
            line.removeprefix("URL: ") for line in user.splitlines() if line.startswith("URL: ")
        )
        custom = per_url.get(url)
        if isinstance(custom, FakeResponse):
            return custom
        return FakeResponse.text(custom or evidence_json(url))

    return respond


def make_pipeline(
    prompts: PromptLoader,
    fake_llm: FakeChatBackend,
    searcher: FakeSearcher,
    fetcher: FakeFetcher,
    **settings: Any,
) -> ResearchPipeline:
    client = LLMClient(
        make_config(),
        prompts=prompts,
        structured_max_retries=0,
        backend_factory=lambda _p: fake_llm,
        recorder=InMemoryRecorder(),
    )
    return ResearchPipeline(
        client,
        prompts,
        searcher,
        fetcher,
        ResearchSettings(min_text_chars=100, **settings),
        today=date(2026, 9, 23),
    )


def test_interleave() -> None:
    a = [hit(1), hit(2), hit(3)]
    b = [hit(4)]
    assert [h.url for h in interleave([a, b])] == [h.url for h in [a[0], b[0], a[1], a[2]]]


async def test_pipeline_end_to_end(prompts: PromptLoader) -> None:
    searcher = FakeSearcher(
        {
            "q1": [hit(1), hit(2), hit(3, title="重複する見出しの記事です")],
            "q2": [hit(1, "q2"), hit(4, "q2", title="重複する見出しの記事です"), hit(5, "q2")],
        }
    )
    irrelevant = "https://site5.example/a"
    unverifiable = "https://site4.example/a"
    missing_quote = "本文にない引用文です。確認できません"
    fake_llm = FakeChatBackend(
        responder=responder_for(
            ["q1", "q2", "q1"],
            {
                irrelevant: evidence_json(irrelevant, relevant=False),
                unverifiable: evidence_json(unverifiable, quote=missing_quote),
            },
        )
    )
    fetcher = FakeFetcher(
        {
            "https://site2.example/a": FetchFailure(
                url="https://site2.example/a", reason="HTTP 404"
            ),
        }
    )
    report = await make_pipeline(prompts, fake_llm, searcher, fetcher).run(TOPIC)

    assert report.queries == ["q1", "q2"]  # 重複クエリは除く
    # 順位ごとに交互に並べた後、2 件目の site1 は URL 重複、site3 は(先に出た site4 と)
    # タイトル重複で除かれる
    assert sorted(fetcher.urls) == [
        "https://site1.example/a",
        "https://site2.example/a",
        "https://site4.example/a",
        "https://site5.example/a",
    ]
    assert [e.id for e in report.evidence] == ["EV-01"]
    (ev,) = report.evidence
    assert ev.source_url == "https://site1.example/a"
    assert ev.published_date == "2025-01-01"
    assert [f.quote_verified for f in ev.key_facts] == [True, False]  # 未検証の事実は明示して残す
    assert len(ev.verified_facts) == 1

    reasons = {s.url: s.reason for s in report.skipped}
    assert reasons["https://site2.example/a"] == "HTTP 404"
    assert "関係が薄い" in reasons[irrelevant]
    assert "引用を本文で確認できる" in reasons[unverifiable]

    # 取得した本文と今日の日付がプロンプトに渡っている
    query_request = fake_llm.requests[0]
    assert "2026-09-23" in query_request.messages[-1].content
    assert any(BODY[:30] in r.messages[-1].content for r in fake_llm.requests[1:])


async def test_pipeline_limits_evidence_and_pages(prompts: PromptLoader) -> None:
    searcher = FakeSearcher({"q1": [hit(n) for n in range(1, 11)]})
    fake_llm = FakeChatBackend(responder=responder_for(["q1"]))
    fetcher = FakeFetcher()
    report = await make_pipeline(
        prompts, fake_llm, searcher, fetcher, max_pages=6, target_evidence=4
    ).run(TOPIC)
    assert len(fetcher.urls) == 6
    assert [e.id for e in report.evidence] == ["EV-01", "EV-02", "EV-03", "EV-04"]
    assert sum("上限" in s.reason for s in report.skipped) == 2


async def test_pipeline_truncates_page_text(prompts: PromptLoader) -> None:
    searcher = FakeSearcher({"q1": [hit(1)]})
    fake_llm = FakeChatBackend(responder=responder_for(["q1"]))
    await make_pipeline(prompts, fake_llm, searcher, FakeFetcher(), max_chars_per_page=500).run(
        TOPIC
    )
    extraction = fake_llm.requests[1].messages[-1].content
    assert page_text("https://site1.example/a")[:500] in extraction
    assert page_text("https://site1.example/a")[:501] not in extraction


async def test_pipeline_skips_short_pages(prompts: PromptLoader) -> None:
    short = FetchedPage(
        url="https://site1.example/a",
        title=None,
        text="短い",
        published_date=None,
        fetched_at=datetime(2026, 9, 1, tzinfo=UTC),
    )
    report = await make_pipeline(
        prompts,
        FakeChatBackend(responder=responder_for(["q1"])),
        FakeSearcher({"q1": [hit(1)]}),
        FakeFetcher({"https://site1.example/a": short}),
    ).run(TOPIC)
    assert report.evidence == []
    assert "短すぎます" in report.skipped[0].reason


async def test_pipeline_skips_page_on_llm_error(prompts: PromptLoader) -> None:
    broken = "https://site1.example/a"
    fake_llm = FakeChatBackend(
        responder=responder_for(
            ["q1"],
            {
                broken: FakeResponse(
                    error=FakeError(kind="other", message="Context size has been exceeded.")
                )
            },
        )
    )
    report = await make_pipeline(
        prompts, fake_llm, FakeSearcher({"q1": [hit(1), hit(2)]}), FakeFetcher()
    ).run(TOPIC)
    assert [e.source_url for e in report.evidence] == ["https://site2.example/a"]
    assert "Context size" in report.skipped[0].reason


async def test_pipeline_aborts_on_llm_connection_error(prompts: PromptLoader) -> None:
    from llm_court.llm import LLMConnectionError

    fake_llm = FakeChatBackend(
        responder=lambda _r: FakeResponse(error=FakeError(kind="connection", message="down"))
    )
    with pytest.raises(LLMConnectionError):
        await make_pipeline(prompts, fake_llm, FakeSearcher({}), FakeFetcher()).run(TOPIC)


async def test_pipeline_tolerates_partial_search_errors(prompts: PromptLoader) -> None:
    searcher = FakeSearcher({"q1": SearchError("q1 失敗"), "q2": [hit(1, "q2")]})
    fake_llm = FakeChatBackend(responder=responder_for(["q1", "q2"]))
    report = await make_pipeline(prompts, fake_llm, searcher, FakeFetcher()).run(TOPIC)
    assert len(report.evidence) == 1


async def test_pipeline_raises_when_all_searches_fail(prompts: PromptLoader) -> None:
    searcher = FakeSearcher({"q1": SearchError("失敗")})
    fake_llm = FakeChatBackend(responder=responder_for(["q1"]))
    with pytest.raises(SearchError):
        await make_pipeline(prompts, fake_llm, searcher, FakeFetcher()).run(TOPIC)
