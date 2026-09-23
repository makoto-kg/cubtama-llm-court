"""実 SearXNG と LLM サーバーを使う捜査パイプラインのテスト。`uv run pytest -m integration`。"""

import httpx
import pytest

from llm_court.config import Settings
from llm_court.llm import LLMClient, PromptLoader
from llm_court.research.cache import PageCache
from llm_court.research.fetch import PageFetcher
from llm_court.research.pipeline import ResearchPipeline
from llm_court.research.search import SearXNGClient

pytestmark = pytest.mark.integration


async def test_live_research() -> None:
    settings = Settings()
    research = settings.research.model_copy(update={"target_evidence": 3, "max_pages": 6})
    async with LLMClient.from_settings(settings) as llm, httpx.AsyncClient() as http:
        pipeline = ResearchPipeline(
            llm,
            PromptLoader(settings.prompts_dir),
            SearXNGClient(settings.searxng_url, timeout_s=research.fetch_timeout_s, client=http),
            PageFetcher(research, client=http, cache=PageCache(research.cache_dir)),
            research,
        )
        report = await pipeline.run("週休3日制を導入すべきか")
    assert report.queries
    assert report.evidence
    assert all(ev.verified_facts for ev in report.evidence)
