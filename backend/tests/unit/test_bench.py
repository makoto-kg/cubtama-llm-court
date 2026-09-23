import json

from llm_court.config import Role
from llm_court.llm import ChatRequest, InMemoryRecorder, LLMClient, PromptLoader
from llm_court.llm.bench import run_bench
from tests.fakes import FakeChatBackend, FakeResponse
from tests.unit.test_llm_client import make_config

VALID = json.dumps(
    {"stance": "賛成", "claim": "主張", "reasons": ["根拠1", "根拠2"], "confidence": 0.5},
    ensure_ascii=False,
)


def bench_responder(request: ChatRequest) -> FakeResponse:
    if request.response_format is not None:
        # "big" モデルは常に不正な JSON を返す
        return FakeResponse.text("{}" if request.model == "big" else VALID)
    return FakeResponse.text("意見です。")


async def test_run_bench_groups_roles_by_model(prompts: PromptLoader) -> None:
    fake = FakeChatBackend(responder=bench_responder)
    recorder = InMemoryRecorder()
    client = LLMClient(
        make_config(),
        prompts=prompts,
        structured_max_retries=1,
        backend_factory=lambda _p: fake,
        recorder=recorder,
    )
    rows = await run_bench(client, recorder, prompts, [Role.DEBATER, Role.JUDGE, Role.ANALYST], 2)

    by_key = {(r.model_key, r.task): r for r in rows}
    assert set(by_key) == {
        ("fast", "text"),
        ("fast", "structured"),
        ("heavy", "text"),
        ("heavy", "structured"),
    }
    assert by_key[("heavy", "text")].roles == ["judge", "analyst"]
    assert by_key[("fast", "structured")].success_rate == 1.0
    assert by_key[("fast", "structured")].modes == {"json_schema": 2}
    failed = by_key[("heavy", "structured")]
    assert failed.successes == 0
    assert failed.runs == 2
    assert failed.mean_retries == 1.0
    assert failed.errors
