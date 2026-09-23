from datetime import UTC, datetime
from pathlib import Path

import pytest

from llm_court.config import ModelsConfig, load_models_config
from llm_court.domain import Evidence, KeyFact, ResearchReport
from llm_court.llm import PromptLoader

BACKEND_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def models_config() -> ModelsConfig:
    return load_models_config(BACKEND_ROOT / "config" / "models.yaml")


@pytest.fixture
def prompts() -> PromptLoader:
    return PromptLoader(BACKEND_ROOT / "prompts")


@pytest.fixture
def research_report() -> ResearchReport:
    fetched = datetime(2026, 9, 1, tzinfo=UTC)
    return ResearchReport(
        topic="ベーシックインカムを導入すべきか",
        created_at=fetched,
        queries=["ベーシックインカム 実験"],
        evidence=[
            Evidence(
                id="EV-01",
                title="フィンランドの給付実験",
                source_url="https://a.example/1",
                retrieved_at=fetched,
                published_date="2020-06-25",
                summary="2年間の給付実験で雇用への影響は小さく、生活満足度は改善した。",
                key_facts=[
                    KeyFact(
                        text="雇用への大きな影響はなかった",
                        quote="雇用には大きな効果は見られなかったが、健康状態や生活満足度は改善した",
                        quote_verified=True,
                    ),
                    KeyFact(text="未検証の事実", quote="就業率が半減した", quote_verified=False),
                ],
            ),
            Evidence(
                id="EV-02",
                title="必要な財源の試算",
                source_url="https://b.example/2",
                retrieved_at=fetched,
                summary="全国民に月10万円を配ると年間約150兆円が必要になる。",
                key_facts=[
                    KeyFact(
                        text="年間約150兆円が必要",
                        quote="単純計算で年間約150兆円が必要になります",
                        quote_verified=True,
                    )
                ],
            ),
        ],
        skipped=[],
    )
