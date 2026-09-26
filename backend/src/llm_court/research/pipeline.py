"""捜査パイプライン: テーマ → 検索クエリ → 検索 → 本文取得 → 証拠品化 → 引用検証。"""

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Protocol

from llm_court.config import ResearchSettings, Role
from llm_court.domain import Evidence, KeyFact, ResearchReport, SkippedSource
from llm_court.llm import LLMClient, LLMConnectionError, LLMError, PromptLoader
from llm_court.research.cache import FetchedPage
from llm_court.research.dedupe import dedupe_hits
from llm_court.research.fetch import FetchFailure
from llm_court.research.quotes import verify_quote
from llm_court.research.schemas import EvidenceDraft, SearchQueries
from llm_court.research.search import SearchError, SearchHit

logger = logging.getLogger(__name__)

ProgressFn = Callable[[str], None]

FOUND_PREFIX = "証拠品候補: "
"""証拠品候補が見つかったときの進捗メッセージの接頭辞(捜査画面で候補を並べるのに使う)。"""


class Searcher(Protocol):
    async def search(self, query: str, *, limit: int) -> list[SearchHit]: ...


class Fetcher(Protocol):
    async def fetch(self, url: str) -> FetchedPage | FetchFailure: ...


def interleave(lists: list[list[SearchHit]]) -> list[SearchHit]:
    """各クエリの結果を順位ごとに交互に並べる(特定のクエリに偏らないように)。"""
    result: list[SearchHit] = []
    for rank in range(max((len(hits) for hits in lists), default=0)):
        result.extend(hits[rank] for hits in lists if rank < len(hits))
    return result


class ResearchPipeline:
    def __init__(
        self,
        llm: LLMClient,
        prompts: PromptLoader,
        searcher: Searcher,
        fetcher: Fetcher,
        settings: ResearchSettings,
        *,
        today: date | None = None,
    ) -> None:
        self._llm = llm
        self._prompts = prompts
        self._searcher = searcher
        self._fetcher = fetcher
        self._settings = settings
        self._today = today or datetime.now(UTC).date()

    async def run(self, topic: str, on_progress: ProgressFn | None = None) -> ResearchReport:
        def progress(message: str) -> None:
            logger.debug(message)
            if on_progress is not None:
                on_progress(message)

        created_at = datetime.now(UTC)
        skipped: list[SkippedSource] = []

        progress("検索クエリを考えています")
        queries = await self._generate_queries(topic)

        progress(f"{len(queries)} 個のクエリで検索しています")
        hits = await self._search_all(queries)
        candidates = dedupe_hits(hits)[: self._settings.max_pages]

        progress(f"{len(candidates)} ページの本文を取得しています")
        fetched = await asyncio.gather(*(self._fetcher.fetch(hit.url) for hit in candidates))
        pages: list[tuple[SearchHit, FetchedPage]] = []
        for hit, result in zip(candidates, fetched, strict=True):
            if isinstance(result, FetchFailure):
                skipped.append(SkippedSource(url=hit.url, reason=result.reason))
            elif len(result.text) < self._settings.min_text_chars:
                reason = f"本文が短すぎます({len(result.text)} 字)"
                skipped.append(SkippedSource(url=hit.url, reason=reason))
            else:
                pages.append((hit, result))

        progress(f"{len(pages)} ページを証拠品にまとめています")
        done = 0

        async def extract(hit: SearchHit, page: FetchedPage) -> EvidenceDraft | str:
            nonlocal done
            try:
                draft = await self._extract(topic, hit, page)
                if draft.relevant:
                    progress(f"{FOUND_PREFIX}{draft.title}")
                return draft
            except LLMConnectionError:
                raise
            except LLMError as e:
                # 構造化出力の失敗やコンテキスト超過などはこのページだけ諦める
                logger.warning("証拠品化に失敗しました: %s (%s)", hit.url, e)
                return f"証拠品化に失敗しました: {e}"
            finally:
                done += 1
                progress(f"証拠品化 {done}/{len(pages)}")

        drafts = await asyncio.gather(*(extract(hit, page) for hit, page in pages))

        evidence: list[Evidence] = []
        for (hit, page), draft in zip(pages, drafts, strict=True):
            if isinstance(draft, str):
                skipped.append(SkippedSource(url=hit.url, reason=draft))
                continue
            if not draft.relevant:
                skipped.append(SkippedSource(url=hit.url, reason="テーマと関係が薄い"))
                continue
            facts = [
                KeyFact(text=f.text, quote=f.quote, quote_verified=verify_quote(f.quote, page.text))
                for f in draft.key_facts
            ]
            if not any(f.quote_verified for f in facts):
                reason = "引用を本文で確認できる事実がありません"
                skipped.append(SkippedSource(url=hit.url, reason=reason))
                continue
            if len(evidence) >= self._settings.target_evidence:
                skipped.append(SkippedSource(url=hit.url, reason="証拠品の上限に達しました"))
                continue
            evidence.append(
                Evidence(
                    id=f"EV-{len(evidence) + 1:02d}",
                    title=draft.title,
                    source_url=page.url,
                    retrieved_at=page.fetched_at,
                    published_date=page.published_date,
                    summary=draft.summary,
                    key_facts=facts,
                )
            )

        return ResearchReport(
            topic=topic,
            created_at=created_at,
            queries=queries,
            evidence=evidence,
            skipped=skipped,
        )

    async def _generate_queries(self, topic: str) -> list[str]:
        prompt = self._prompts.render(
            "researcher/queries",
            topic=topic,
            today=self._today.isoformat(),
            count=self._settings.query_count,
        )
        result = await self._llm.generate_structured(Role.RESEARCHER, prompt, SearchQueries)
        queries = list(dict.fromkeys(q.strip() for q in result.value.queries if q.strip()))
        return queries[: self._settings.query_count]

    async def _search_all(self, queries: list[str]) -> list[SearchHit]:
        limit = self._settings.search_results_per_query
        results = await asyncio.gather(
            *(self._searcher.search(q, limit=limit) for q in queries), return_exceptions=True
        )
        hit_lists: list[list[SearchHit]] = []
        errors: list[BaseException] = []
        for result in results:
            if isinstance(result, SearchError):
                logger.warning("%s", result)
                errors.append(result)
            elif isinstance(result, BaseException):
                raise result
            else:
                hit_lists.append(result)
        if not hit_lists and errors:
            raise errors[0]
        return interleave(hit_lists)

    async def _extract(self, topic: str, hit: SearchHit, page: FetchedPage) -> EvidenceDraft:
        prompt = self._prompts.render(
            "researcher/evidence",
            topic=topic,
            page_title=hit.title or page.title or "",
            url=page.url,
            published_date=page.published_date,
            text=page.text[: self._settings.max_chars_per_page],
        )
        result = await self._llm.generate_structured(Role.RESEARCHER, prompt, EvidenceDraft)
        return result.value
