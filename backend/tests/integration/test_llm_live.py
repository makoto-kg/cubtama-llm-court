"""実 LLM サーバーを使うテスト。`uv run pytest -m integration` で実行する。"""

import pytest

from llm_court.config import Role, Settings
from llm_court.llm import InMemoryRecorder, LLMClient, PromptLoader
from llm_court.llm.bench import BenchArgument

pytestmark = pytest.mark.integration

ROLE = Role.DEBATER


async def test_live_text_and_structured() -> None:
    settings = Settings()
    recorder = InMemoryRecorder()
    prompts = PromptLoader(settings.prompts_dir)
    async with LLMClient.from_settings(settings, recorder=recorder) as client:
        text = await client.generate_text(
            ROLE,
            prompts.render("bench/free", topic="リモートワークは生産性を高める", stance="賛成"),
        )
        assert text.text
        assert "<think>" not in text.text

        result = await client.generate_structured(
            ROLE,
            prompts.render("bench/structured", topic="原子力発電を拡大すべきだ", stance="反対"),
            BenchArgument,
        )
        assert result.value.stance in ("賛成", "反対")
    assert all(r.success for r in recorder.records)
