"""ページ本文の取得と抽出(robots.txt 確認、タイムアウト・サイズ上限、キャッシュ)。"""

import asyncio
import logging
from datetime import UTC, datetime
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx
import trafilatura
from pydantic import BaseModel, ConfigDict

from llm_court.config import ResearchSettings
from llm_court.research.cache import FetchedPage, PageCache

logger = logging.getLogger(__name__)


class FetchFailure(BaseModel):
    model_config = ConfigDict(frozen=True)

    url: str
    reason: str


class _Extracted(BaseModel):
    title: str | None
    text: str
    published_date: str | None


def extract_page(html: bytes | str, url: str) -> _Extracted | None:
    """HTML から本文・タイトル・公開日を抽出する(同期、CPU 処理)。"""
    document = trafilatura.bare_extraction(
        html,
        url=url,
        with_metadata=True,
        include_comments=False,
        include_tables=True,
        favor_precision=True,
    )
    if document is None or isinstance(document, dict):
        return None
    text = document.text or ""
    if not text.strip():
        return None
    return _Extracted(title=document.title, text=text, published_date=document.date)


class PageFetcher:
    def __init__(
        self,
        settings: ResearchSettings,
        *,
        client: httpx.AsyncClient,
        cache: PageCache,
    ) -> None:
        self._settings = settings
        self._client = client
        self._cache = cache
        self._robots: dict[str, RobotFileParser | None] = {}
        self._robots_lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(settings.fetch_concurrency)
        self.cache_hits = 0

    async def _robots_for(self, url: str) -> RobotFileParser | None:
        """ホストの robots.txt。取得できない場合は None(制限なしとして扱う)。"""
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        async with self._robots_lock:
            if origin in self._robots:
                return self._robots[origin]
            parser: RobotFileParser | None = None
            try:
                response = await self._client.get(
                    f"{origin}/robots.txt",
                    headers={"User-Agent": self._settings.user_agent},
                    timeout=self._settings.fetch_timeout_s,
                    follow_redirects=True,
                )
                if response.status_code in (401, 403):
                    parser = RobotFileParser()
                    parser.parse(["User-agent: *", "Disallow: /"])
                elif response.is_success:
                    parser = RobotFileParser()
                    parser.parse(response.text.splitlines())
            except httpx.HTTPError as e:
                logger.debug("robots.txt を取得できません: %s (%s)", origin, e)
            self._robots[origin] = parser
            return parser

    async def fetch(self, url: str) -> FetchedPage | FetchFailure:
        cached = self._cache.get(url)
        if cached is not None:
            self.cache_hits += 1
            return cached
        async with self._semaphore:
            robots = await self._robots_for(url)
            if robots is not None and not robots.can_fetch(self._settings.user_agent, url):
                return FetchFailure(url=url, reason="robots.txt で禁止されています")
            try:
                body = await self._download(url)
            except httpx.HTTPError as e:
                return FetchFailure(url=url, reason=f"取得に失敗しました: {type(e).__name__}")
            if isinstance(body, FetchFailure):
                return body
        extracted = await asyncio.to_thread(extract_page, body, url)
        if extracted is None:
            return FetchFailure(url=url, reason="本文を抽出できませんでした")
        page = FetchedPage(
            url=url,
            title=extracted.title,
            text=extracted.text,
            published_date=extracted.published_date,
            fetched_at=datetime.now(UTC),
        )
        self._cache.put(page)
        return page

    async def _download(self, url: str) -> bytes | FetchFailure:
        limit = self._settings.fetch_max_bytes
        async with self._client.stream(
            "GET",
            url,
            headers={"User-Agent": self._settings.user_agent, "Accept-Language": "ja,en;q=0.5"},
            timeout=self._settings.fetch_timeout_s,
            follow_redirects=True,
        ) as response:
            if not response.is_success:
                return FetchFailure(url=url, reason=f"HTTP {response.status_code}")
            content_type = response.headers.get("content-type", "")
            if "html" not in content_type.lower():
                return FetchFailure(
                    url=url, reason=f"HTML ではありません({content_type or '不明'})"
                )
            declared = response.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > limit:
                return FetchFailure(url=url, reason="サイズ上限を超えています")
            chunks: list[bytes] = []
            size = 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > limit:
                    return FetchFailure(url=url, reason="サイズ上限を超えています")
                chunks.append(chunk)
        return b"".join(chunks)
