"""OpenAI 互換 API との通信。

`LLMClient` は `ChatBackend` プロトコル越しにサーバーを呼ぶ。テストでは録画済み応答を返す
フェイク実装に差し替える。
"""

from collections.abc import AsyncIterator
from typing import Any, Literal, Protocol, cast

import openai
from openai import AsyncStream
from openai.types.chat import (
    ChatCompletion,
    ChatCompletionChunk,
    ChatCompletionMessageParam,
    completion_create_params,
)
from pydantic import BaseModel, ConfigDict

from llm_court.config import ProviderConfig
from llm_court.llm.errors import LLMConnectionError, LLMError, LLMRequestRejectedError


class ChatMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: Literal["system", "user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    model: str
    messages: list[ChatMessage]
    response_format: dict[str, Any] | None = None
    reasoning_effort: Literal["low", "medium", "high"] | None = None
    max_tokens: int | None = None


class Usage(BaseModel):
    model_config = ConfigDict(frozen=True)

    input_tokens: int
    output_tokens: int


class ChatChunk(BaseModel):
    """応答の断片。`reasoning` は本文と分けて返された思考部分。"""

    model_config = ConfigDict(frozen=True)

    content: str = ""
    reasoning: str = ""
    usage: Usage | None = None


class ChatBackend(Protocol):
    def stream(self, request: ChatRequest) -> AsyncIterator[ChatChunk]:
        """ストリーミングで応答を返す。"""
        ...

    async def complete(self, request: ChatRequest) -> ChatChunk:
        """非ストリーミングで応答全体を返す。"""
        ...

    async def aclose(self) -> None: ...


def _reasoning_of(extra: dict[str, Any] | None) -> str:
    # サーバーによって reasoning_content / reasoning のどちらかで返る
    if not extra:
        return ""
    for key in ("reasoning_content", "reasoning"):
        value = extra.get(key)
        if isinstance(value, str):
            return value
    return ""


def _map_error(e: openai.OpenAIError) -> LLMError:
    if isinstance(e, openai.APIConnectionError):
        return LLMConnectionError(f"LLM サーバーに接続できません: {e}")
    if isinstance(e, openai.BadRequestError | openai.UnprocessableEntityError):
        return LLMRequestRejectedError(f"リクエストが拒否されました: {e}", e.status_code)
    return LLMError(f"LLM 呼び出しに失敗しました: {e}")


class OpenAIChatBackend:
    """openai 公式 SDK で OpenAI 互換サーバーを呼ぶ。"""

    def __init__(self, provider: ProviderConfig) -> None:
        self._client = openai.AsyncOpenAI(
            base_url=provider.base_url,
            api_key=provider.api_key.get_secret_value(),
            timeout=provider.timeout_s,
            max_retries=0,  # 再試行は LLMClient 側で制御する
        )

    @classmethod
    def from_provider(cls, provider: ProviderConfig) -> "OpenAIChatBackend":
        return cls(provider)

    async def _create(self, request: ChatRequest, *, stream: bool) -> Any:
        messages = cast(
            list[ChatCompletionMessageParam], [m.model_dump() for m in request.messages]
        )
        response_format = (
            cast(completion_create_params.ResponseFormat, request.response_format)
            if request.response_format is not None
            else openai.omit
        )
        return await self._client.chat.completions.create(
            model=request.model,
            messages=messages,
            response_format=response_format,
            reasoning_effort=request.reasoning_effort or openai.omit,
            max_tokens=request.max_tokens if request.max_tokens is not None else openai.omit,
            stream=stream,
            stream_options={"include_usage": True} if stream else openai.omit,
        )

    async def stream(self, request: ChatRequest) -> AsyncIterator[ChatChunk]:
        try:
            stream = cast(
                AsyncStream[ChatCompletionChunk], await self._create(request, stream=True)
            )
            async for chunk in stream:
                content = ""
                reasoning = ""
                if chunk.choices:
                    delta = chunk.choices[0].delta
                    content = delta.content or ""
                    reasoning = _reasoning_of(delta.model_extra)
                usage = (
                    Usage(
                        input_tokens=chunk.usage.prompt_tokens,
                        output_tokens=chunk.usage.completion_tokens,
                    )
                    if chunk.usage
                    else None
                )
                if content or reasoning or usage:
                    yield ChatChunk(content=content, reasoning=reasoning, usage=usage)
        except openai.OpenAIError as e:
            raise _map_error(e) from e

    async def complete(self, request: ChatRequest) -> ChatChunk:
        try:
            response = cast(ChatCompletion, await self._create(request, stream=False))
        except openai.OpenAIError as e:
            raise _map_error(e) from e
        message = response.choices[0].message if response.choices else None
        usage = (
            Usage(
                input_tokens=response.usage.prompt_tokens,
                output_tokens=response.usage.completion_tokens,
            )
            if response.usage
            else None
        )
        return ChatChunk(
            content=(message.content or "") if message else "",
            reasoning=_reasoning_of(message.model_extra) if message else "",
            usage=usage,
        )

    async def aclose(self) -> None:
        await self._client.close()
