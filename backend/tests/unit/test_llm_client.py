import asyncio
from typing import Any

import pytest

from llm_court.config import ModelsConfig, Role
from llm_court.llm import (
    ChatMessage,
    InMemoryRecorder,
    LLMClient,
    LLMConnectionError,
    PromptLoader,
    StructuredOutputError,
)
from llm_court.llm.bench import BenchArgument
from tests.fakes import FakeChatBackend, FakeError, FakeResponse, load_recording

MESSAGES = [ChatMessage(role="user", content="論題について答えて")]


def make_config(
    *,
    json_schema: bool = True,
    json_mode: bool = False,
    streaming: bool = True,
    max_concurrency: int = 2,
) -> ModelsConfig:
    return ModelsConfig.model_validate(
        {
            "providers": {
                "local": {
                    "base_url": "http://localhost:1234/v1",
                    "capabilities": {
                        "json_schema": json_schema,
                        "json_mode": json_mode,
                        "streaming": streaming,
                    },
                    "max_concurrency": max_concurrency,
                }
            },
            "models": {
                "heavy": {"provider": "local", "model": "big", "reasoning": "high"},
                "fast": {"provider": "local", "model": "small"},
            },
            "roles": {r.value: ("fast" if r is Role.DEBATER else "heavy") for r in Role},
        }
    )


def make_client(
    fake: FakeChatBackend,
    prompts: PromptLoader,
    *,
    max_retries: int = 2,
    **config: Any,
) -> tuple[LLMClient, InMemoryRecorder]:
    recorder = InMemoryRecorder()
    client = LLMClient(
        make_config(**config),
        prompts=prompts,
        structured_max_retries=max_retries,
        backend_factory=lambda _p: fake,
        recorder=recorder,
    )
    return client, recorder


# --- 自由生成 ---


async def test_stream_text_strips_think_and_records(prompts: PromptLoader) -> None:
    fake = FakeChatBackend(load_recording("text_with_think"))
    client, recorder = make_client(fake, prompts)
    parts = [p async for p in client.stream_text(Role.DEBATER, MESSAGES)]
    assert "".join(parts) == "賛成です。理由は二つあります。"
    assert all("think" not in p for p in parts)

    (record,) = recorder.records
    assert record.kind == "text"
    assert record.role == "debater"
    assert record.model == "small"
    assert record.success
    assert record.input_tokens == 80
    assert record.output_tokens == 30
    assert record.ttft_ms is not None and record.ttft_ms >= 0
    assert record.total_ms >= record.ttft_ms


async def test_generate_text_passes_model_and_reasoning(prompts: PromptLoader) -> None:
    fake = FakeChatBackend([FakeResponse.text("判決を言い渡します。")])
    client, _ = make_client(fake, prompts)
    rendered = prompts.render("bench/free", topic="論題", stance="賛成")
    result = await client.generate_text(Role.JUDGE, rendered)
    assert result.text == "判決を言い渡します。"
    assert result.record.prompt_name == "bench/free"
    assert result.record.prompt_version == rendered.version
    (request,) = fake.requests
    assert request.model == "big"
    assert request.reasoning_effort == "high"
    assert request.messages[0].role == "system"


async def test_non_streaming_provider_uses_complete(prompts: PromptLoader) -> None:
    fake = FakeChatBackend([FakeResponse.text("<think>x</think>本文")])
    client, recorder = make_client(fake, prompts, streaming=False)
    result = await client.generate_text(Role.DEBATER, MESSAGES)
    assert result.text == "本文"
    assert recorder.records[0].output_tokens == 10


async def test_connection_error_is_recorded_and_raised(prompts: PromptLoader) -> None:
    fake = FakeChatBackend([FakeResponse(error=FakeError(kind="connection", message="down"))])
    client, recorder = make_client(fake, prompts)
    with pytest.raises(LLMConnectionError):
        await client.generate_text(Role.DEBATER, MESSAGES)
    (record,) = recorder.records
    assert not record.success
    assert record.error == "down"


async def test_concurrency_is_limited_per_provider(prompts: PromptLoader) -> None:
    fake = FakeChatBackend(FakeResponse(chunks=[], delay_s=0.02) for _ in range(6))
    client, recorder = make_client(fake, prompts, max_concurrency=2)
    await asyncio.gather(*(client.generate_text(Role.DEBATER, MESSAGES) for _ in range(6)))
    assert fake.max_active == 2
    assert len(recorder.records) == 6


async def test_aclose_closes_backends(prompts: PromptLoader) -> None:
    fake = FakeChatBackend()
    client, _ = make_client(fake, prompts)
    async with client:
        pass
    assert fake.closed


# --- 構造化出力 ---


@pytest.mark.parametrize(
    ("caps", "expected"),
    [
        ({"json_schema": True, "json_mode": True}, ["json_schema", "json_object", "prompt"]),
        ({"json_schema": True, "json_mode": False}, ["json_schema", "prompt"]),
        ({"json_schema": False, "json_mode": True}, ["json_object", "prompt"]),
        ({"json_schema": False, "json_mode": False}, ["prompt"]),
    ],
)
def test_structured_modes_follow_capabilities(
    prompts: PromptLoader, caps: dict[str, bool], expected: list[str]
) -> None:
    client, _ = make_client(FakeChatBackend(), prompts, **caps)
    assert client.structured_modes(Role.JUDGE) == expected


async def test_structured_json_schema_success(prompts: PromptLoader) -> None:
    fake = FakeChatBackend(load_recording("structured_success"))
    client, recorder = make_client(fake, prompts)
    result = await client.generate_structured(Role.DEBATER, MESSAGES, BenchArgument)

    assert result.value.stance == "賛成"
    assert result.value.reasons == ["通勤時間の削減", "割り込みの減少"]
    (request,) = fake.requests
    assert request.response_format is not None
    assert request.response_format["type"] == "json_schema"
    assert request.response_format["json_schema"]["name"] == "BenchArgument"
    # json_schema モードではスキーマ指示をプロンプトに足さない
    assert request.messages == MESSAGES

    (record,) = recorder.records
    assert record.kind == "structured"
    assert record.success
    assert record.structured_mode == "json_schema"
    assert record.schema_name == "BenchArgument"
    assert record.retries == 0
    assert record.attempts == 1
    assert record.output_tokens == 48


async def test_structured_retry_with_feedback(prompts: PromptLoader) -> None:
    fake = FakeChatBackend(load_recording("structured_retry"))
    client, recorder = make_client(fake, prompts)
    result = await client.generate_structured(Role.DEBATER, MESSAGES, BenchArgument)

    assert result.value.reasons == ["通勤がない", "集中しやすい"]
    first, second = fake.requests
    assert len(second.messages) == len(first.messages) + 2
    assistant, feedback = second.messages[-2:]
    assert assistant.role == "assistant"
    assert "think" not in assistant.content  # 思考部分はフィードバックに含めない
    assert feedback.role == "user"
    assert "直前の出力" in feedback.content
    assert "reasons" in feedback.content

    (record,) = recorder.records
    assert record.success
    assert record.retries == 1
    assert record.attempts == 2
    assert record.output_tokens == 78  # 全試行の合計


async def test_structured_downgrades_when_mode_rejected(prompts: PromptLoader) -> None:
    fake = FakeChatBackend(load_recording("schema_rejected"))
    client, recorder = make_client(fake, prompts)
    result = await client.generate_structured(Role.DEBATER, MESSAGES, BenchArgument)

    assert result.value.stance == "反対"
    first, second = fake.requests
    assert first.response_format is not None
    assert second.response_format is None  # prompt モード
    assert second.messages[0].role == "system"
    assert "JSON Schema" in second.messages[0].content

    (record,) = recorder.records
    assert record.structured_mode == "prompt"
    assert record.retries == 0  # 降格は再試行に数えない
    assert record.attempts == 2


async def test_structured_json_object_mode(prompts: PromptLoader) -> None:
    valid = load_recording("structured_success")[0]
    fake = FakeChatBackend([valid])
    client, _ = make_client(fake, prompts, json_schema=False, json_mode=True)
    await client.generate_structured(Role.DEBATER, MESSAGES, BenchArgument)
    (request,) = fake.requests
    assert request.response_format == {"type": "json_object"}
    assert "JSON Schema" in request.messages[0].content


async def test_structured_gives_up_after_max_retries(prompts: PromptLoader) -> None:
    fake = FakeChatBackend(FakeResponse.text("JSON ではない返答") for _ in range(3))
    client, recorder = make_client(fake, prompts, max_retries=2)
    with pytest.raises(StructuredOutputError) as exc_info:
        await client.generate_structured(Role.DEBATER, MESSAGES, BenchArgument)

    assert len(fake.requests) == 3
    assert len(exc_info.value.attempts) == 3
    (record,) = recorder.records
    assert not record.success
    assert record.retries == 2
    assert record.error is not None


async def test_structured_all_modes_rejected(prompts: PromptLoader) -> None:
    rejected = FakeResponse(error=FakeError(kind="rejected"))
    fake = FakeChatBackend([rejected, rejected])
    client, recorder = make_client(fake, prompts)
    with pytest.raises(StructuredOutputError, match="拒否"):
        await client.generate_structured(Role.DEBATER, MESSAGES, BenchArgument)
    assert not recorder.records[0].success


async def test_structured_connection_error_is_not_retried(prompts: PromptLoader) -> None:
    fake = FakeChatBackend([FakeResponse(error=FakeError(kind="connection"))])
    client, recorder = make_client(fake, prompts)
    with pytest.raises(LLMConnectionError):
        await client.generate_structured(Role.DEBATER, MESSAGES, BenchArgument)
    assert len(fake.requests) == 1
    assert not recorder.records[0].success
