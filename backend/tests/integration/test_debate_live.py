"""実 LLM サーバーでディベートを 1 往復行うテスト。`uv run pytest -m integration`。"""

import json
from pathlib import Path

import pytest

from llm_court.config import Settings
from llm_court.domain import ResearchReport
from llm_court.engine.debate import DebateEngine
from llm_court.engine.recorder import BufferedRecorder
from llm_court.engine.store import EventStore
from llm_court.llm import LLMClient, PromptLoader
from llm_court.modes import DEBATE_MODE

pytestmark = pytest.mark.integration

FIXTURE = Path(__file__).parents[1] / "fixtures" / "research" / "report.json"


async def test_live_debate() -> None:
    settings = Settings()
    report = ResearchReport.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))
    recorder = BufferedRecorder()
    store = await EventStore.open(None)
    try:
        async with LLMClient.from_settings(settings, recorder=recorder) as llm:
            engine = DebateEngine(
                llm=llm,
                recorder=recorder,
                prompts=PromptLoader(settings.prompts_dir),
                store=store,
                mode=DEBATE_MODE,
            )
            state = await engine.run(report.topic, 1, evidence=report)
    finally:
        await store.aclose()
    assert len(state.statements) == 6
    assert state.verdict is not None
