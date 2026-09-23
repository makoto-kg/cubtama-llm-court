import httpx
import pytest

from llm_court.research.search import SearchError, SearXNGClient


def _client(handler: httpx.MockTransport) -> SearXNGClient:
    return SearXNGClient(
        "http://searx.test/", timeout_s=5, client=httpx.AsyncClient(transport=handler)
    )


async def test_search_parses_results() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "results": [
                    {"url": "https://a.example/1", "title": "A", "content": "要約", "engine": "x"},
                    {"url": "ftp://bad.example/", "title": "対象外"},
                    {"url": "https://b.example/2", "title": None},
                    {"url": "https://c.example/3", "title": "C"},
                ]
            },
        )

    hits = await _client(httpx.MockTransport(handler)).search("ベーシックインカム", limit=2)
    assert [h.url for h in hits] == ["https://a.example/1", "https://b.example/2"]
    assert hits[0].snippet == "要約"
    assert hits[1].title == ""
    assert hits[0].query == "ベーシックインカム"
    (request,) = seen
    assert request.url.path == "/search"
    assert request.url.params["format"] == "json"
    assert request.url.params["q"] == "ベーシックインカム"


async def test_search_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="forbidden")

    with pytest.raises(SearchError):
        await _client(httpx.MockTransport(handler)).search("q", limit=5)


async def test_search_connection_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    with pytest.raises(SearchError, match="SearXNG"):
        await _client(httpx.MockTransport(handler)).search("q", limit=5)
