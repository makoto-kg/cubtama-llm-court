from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from llm_court.config import ResearchSettings
from llm_court.research.cache import FetchedPage, PageCache
from llm_court.research.fetch import FetchFailure, PageFetcher

ARTICLE = (Path(__file__).parents[1] / "fixtures" / "research" / "article.html").read_bytes()
URL = "https://news.example/articles/1"
EMPTY_HTML = b"<html><body></body></html>"

Handler = Callable[[httpx.Request], httpx.Response]


def site(robots: str | None = None, page: httpx.Response | None = None) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=robots) if robots else httpx.Response(404)
        if page is not None:
            return page
        return httpx.Response(200, content=ARTICLE, headers={"content-type": "text/html"})

    return handler


def make_fetcher(
    tmp_path: Path, handler: Handler, **overrides: object
) -> tuple[PageFetcher, list[httpx.Request]]:
    requests: list[httpx.Request] = []

    def recording(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    settings = ResearchSettings(cache_dir=tmp_path, **overrides)  # type: ignore[arg-type]
    fetcher = PageFetcher(
        settings,
        client=httpx.AsyncClient(transport=httpx.MockTransport(recording)),
        cache=PageCache(tmp_path),
    )
    return fetcher, requests


async def test_fetch_extracts_article(tmp_path: Path) -> None:
    fetcher, requests = make_fetcher(tmp_path, site())
    page = await fetcher.fetch(URL)
    assert isinstance(page, FetchedPage)
    assert "失業者2,000人" in page.text
    assert "トップ" not in page.text  # ナビゲーションは除かれる
    assert page.published_date == "2025-04-01"
    assert requests[-1].headers["user-agent"].startswith("llm-court-research")


async def test_fetch_uses_cache(tmp_path: Path) -> None:
    fetcher, requests = make_fetcher(tmp_path, site())
    await fetcher.fetch(URL)
    count = len(requests)

    fetcher2, requests2 = make_fetcher(tmp_path, site())
    page = await fetcher2.fetch(URL)
    assert isinstance(page, FetchedPage)
    assert requests2 == []
    assert fetcher2.cache_hits == 1
    assert count >= 1


async def test_fetch_respects_robots(tmp_path: Path) -> None:
    fetcher, requests = make_fetcher(tmp_path, site(robots="User-agent: *\nDisallow: /articles/"))
    result = await fetcher.fetch(URL)
    assert isinstance(result, FetchFailure)
    assert "robots" in result.reason
    assert [r.url.path for r in requests] == ["/robots.txt"]


async def test_robots_is_cached_per_host(tmp_path: Path) -> None:
    fetcher, requests = make_fetcher(tmp_path, site(robots="User-agent: *\nAllow: /"))
    await fetcher.fetch(URL)
    await fetcher.fetch("https://news.example/articles/2")
    assert [r.url.path for r in requests].count("/robots.txt") == 1


@pytest.mark.parametrize(
    ("response", "reason"),
    [
        (httpx.Response(404), "HTTP 404"),
        (httpx.Response(200, content=b"%PDF", headers={"content-type": "application/pdf"}), "HTML"),
        (
            httpx.Response(200, content=b"<p>x</p>" * 1000, headers={"content-type": "text/html"}),
            "サイズ上限",
        ),
        (
            httpx.Response(
                200, content=b"<html><body></body></html>", headers={"content-type": "text/html"}
            ),
            "本文を抽出",
        ),
    ],
)
async def test_fetch_failures(tmp_path: Path, response: httpx.Response, reason: str) -> None:
    fetcher, _ = make_fetcher(tmp_path, site(page=response), fetch_max_bytes=2000)
    result = await fetcher.fetch(URL)
    assert isinstance(result, FetchFailure)
    assert reason in result.reason


async def test_fetch_network_error(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timeout", request=request)

    fetcher, _ = make_fetcher(tmp_path, handler)
    result = await fetcher.fetch(URL)
    assert isinstance(result, FetchFailure)
    assert "ConnectTimeout" in result.reason
