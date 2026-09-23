"""役割名で呼び出す LLM クライアント。

役割から設定でモデル・プロバイダを解決し、並列度制御・思考部分の除去・構造化出力の
フォールバックと再試行・計測記録をここで一元的に行う。
"""

import asyncio
import json
import time
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ValidationError

from llm_court.config import ModelsConfig, ProviderConfig, ResolvedModel, Role, Settings
from llm_court.config.models_config import load_models_config
from llm_court.llm.backend import (
    ChatBackend,
    ChatChunk,
    ChatMessage,
    ChatRequest,
    OpenAIChatBackend,
)
from llm_court.llm.errors import LLMError, LLMRequestRejectedError, StructuredOutputError
from llm_court.llm.metrics import CallRecorder, InMemoryRecorder, LLMCallRecord, StructuredMode
from llm_court.llm.preprocess import ThinkFilter, extract_json, strip_reasoning
from llm_court.llm.prompts import PromptLoader, RenderedPrompt

BackendFactory = Callable[[ProviderConfig], ChatBackend]
PromptInput = RenderedPrompt | Sequence[ChatMessage]

_MAX_FEEDBACK_CHARS = 1500


@dataclass(frozen=True)
class TextResult:
    text: str
    record: LLMCallRecord


@dataclass(frozen=True)
class StructuredResult[T: BaseModel]:
    value: T
    raw_text: str
    record: LLMCallRecord


@dataclass
class _Attempt:
    """1 回の HTTP 呼び出しの計測。"""

    started: float = field(default_factory=time.perf_counter)
    first_token: float | None = None
    ended: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    def observe(self, chunk: ChatChunk) -> None:
        if self.first_token is None and (chunk.content or chunk.reasoning):
            self.first_token = time.perf_counter()
        if chunk.usage is not None:
            self.input_tokens = chunk.usage.input_tokens
            self.output_tokens = chunk.usage.output_tokens

    def finish(self) -> None:
        self.ended = time.perf_counter()

    @property
    def generation_s(self) -> float | None:
        if self.first_token is None or self.ended is None:
            return None
        return self.ended - self.first_token


@dataclass
class _CallMeter:
    """1 回の論理呼び出し(再試行を含む)の計測を集約する。"""

    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started: float = field(default_factory=time.perf_counter)
    attempts: list[_Attempt] = field(default_factory=list[_Attempt])

    def new_attempt(self) -> _Attempt:
        attempt = _Attempt()
        self.attempts.append(attempt)
        return attempt

    def summary(self) -> dict[str, Any]:
        first = self.attempts[0] if self.attempts else None
        ttft_ms = (
            (first.first_token - first.started) * 1000
            if first is not None and first.first_token is not None
            else None
        )
        input_tokens = _sum_or_none([a.input_tokens for a in self.attempts])
        output_tokens = _sum_or_none([a.output_tokens for a in self.attempts])
        gen_times = [a.generation_s for a in self.attempts]
        tokens_per_s = None
        if output_tokens is not None and all(t is not None for t in gen_times):
            gen_total = sum(t for t in gen_times if t is not None)
            if gen_total > 0:
                tokens_per_s = output_tokens / gen_total
        return {
            "started_at": self.started_at,
            "ttft_ms": ttft_ms,
            "total_ms": (time.perf_counter() - self.started) * 1000,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "tokens_per_s": tokens_per_s,
            "attempts": max(len(self.attempts), 1),
        }


def _sum_or_none(values: list[int | None]) -> int | None:
    if not values or any(v is None for v in values):
        return None
    return sum(v for v in values if v is not None)


def _to_messages(prompt: PromptInput) -> list[ChatMessage]:
    return prompt.to_messages() if isinstance(prompt, RenderedPrompt) else list(prompt)


def _with_instruction(messages: list[ChatMessage], instruction: str) -> list[ChatMessage]:
    """system メッセージの末尾に指示を足す(固定部分を先頭に保つため末尾に置く)。"""
    if messages and messages[0].role == "system":
        head = ChatMessage(role="system", content=f"{messages[0].content}\n\n{instruction}")
        return [head, *messages[1:]]
    return [ChatMessage(role="system", content=instruction), *messages]


def _truncate(text: str, limit: int = _MAX_FEEDBACK_CHARS) -> str:
    return text if len(text) <= limit else text[:limit] + "…"


class LLMClient:
    """役割名で LLM を呼び出す。"""

    def __init__(
        self,
        config: ModelsConfig,
        *,
        prompts: PromptLoader,
        structured_max_retries: int,
        backend_factory: BackendFactory = OpenAIChatBackend.from_provider,
        recorder: CallRecorder | None = None,
    ) -> None:
        self._config = config
        self._prompts = prompts
        self._max_retries = structured_max_retries
        self.recorder: CallRecorder = recorder if recorder is not None else InMemoryRecorder()
        self._backends = {key: backend_factory(p) for key, p in config.providers.items()}
        self._semaphores = {
            key: asyncio.Semaphore(p.max_concurrency) for key, p in config.providers.items()
        }

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        *,
        backend_factory: BackendFactory = OpenAIChatBackend.from_provider,
        recorder: CallRecorder | None = None,
    ) -> "LLMClient":
        return cls(
            load_models_config(settings.models_config_path),
            prompts=PromptLoader(settings.prompts_dir),
            structured_max_retries=settings.llm_structured_max_retries,
            backend_factory=backend_factory,
            recorder=recorder,
        )

    @property
    def config(self) -> ModelsConfig:
        return self._config

    async def aclose(self) -> None:
        for backend in self._backends.values():
            await backend.aclose()

    async def __aenter__(self) -> "LLMClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    # --- 低レベル呼び出し ---

    def _request(
        self,
        resolved: ResolvedModel,
        messages: list[ChatMessage],
        *,
        response_format: dict[str, Any] | None = None,
        max_tokens: int | None = None,
    ) -> ChatRequest:
        return ChatRequest(
            model=resolved.model.model,
            messages=messages,
            response_format=response_format,
            reasoning_effort=resolved.model.reasoning,
            max_tokens=max_tokens,
        )

    async def _chunks(
        self, resolved: ResolvedModel, request: ChatRequest, attempt: _Attempt
    ) -> AsyncIterator[ChatChunk]:
        """並列度制御下でバックエンドを呼び、チャンクを計測しながら返す。"""
        backend = self._backends[resolved.provider_key]
        async with self._semaphores[resolved.provider_key]:
            attempt.started = time.perf_counter()
            try:
                if resolved.provider.capabilities.streaming:
                    async for chunk in backend.stream(request):
                        attempt.observe(chunk)
                        yield chunk
                else:
                    chunk = await backend.complete(request)
                    attempt.observe(chunk)
                    yield chunk
            finally:
                attempt.finish()

    def _record(
        self,
        resolved: ResolvedModel,
        meter: _CallMeter,
        prompt: PromptInput,
        **fields: Any,
    ) -> LLMCallRecord:
        rendered = prompt if isinstance(prompt, RenderedPrompt) else None
        record = LLMCallRecord(
            role=resolved.role.value,
            model_key=resolved.model_key,
            model=resolved.model.model,
            provider=resolved.provider_key,
            prompt_name=rendered.name if rendered else None,
            prompt_version=rendered.version if rendered else None,
            **meter.summary(),
            **fields,
        )
        self.recorder.record(record)
        return record

    # --- 自由生成 ---

    async def _text_stream(
        self,
        role: Role,
        prompt: PromptInput,
        max_tokens: int | None,
        on_record: Callable[[LLMCallRecord], None] | None,
    ) -> AsyncIterator[str]:
        resolved = self._config.resolve(role)
        request = self._request(resolved, _to_messages(prompt), max_tokens=max_tokens)
        meter = _CallMeter()
        attempt = meter.new_attempt()
        think = ThinkFilter()
        started = False
        error: str | None = None
        try:
            async for chunk in self._chunks(resolved, request, attempt):
                if not chunk.content:
                    continue
                out = think.feed(chunk.content)
                if not started:
                    out = out.lstrip()
                    started = bool(out)
                if out:
                    yield out
            tail = think.flush()
            if not started:
                tail = tail.lstrip()
            if tail:
                yield tail
        except LLMError as e:
            error = str(e)
            raise
        except GeneratorExit:
            error = "呼び出し側で中断されました"
            raise
        finally:
            record = self._record(
                resolved, meter, prompt, kind="text", success=error is None, error=error
            )
            if on_record is not None:
                on_record(record)

    def stream_text(
        self, role: Role, prompt: PromptInput, *, max_tokens: int | None = None
    ) -> AsyncIterator[str]:
        """思考部分を除いた本文をチャンクごとに返す。終了時に計測を記録する。"""
        return self._text_stream(role, prompt, max_tokens, None)

    async def generate_text(
        self, role: Role, prompt: PromptInput, *, max_tokens: int | None = None
    ) -> TextResult:
        records: list[LLMCallRecord] = []
        parts = [part async for part in self._text_stream(role, prompt, max_tokens, records.append)]
        return TextResult(text="".join(parts).strip(), record=records[0])

    # --- 構造化出力 ---

    def structured_modes(self, role: Role) -> list[StructuredMode]:
        """能力フラグから試すモードの順序を決める。"""
        caps = self._config.resolve(role).provider.capabilities
        modes: list[StructuredMode] = []
        if caps.json_schema:
            modes.append("json_schema")
        if caps.json_mode:
            modes.append("json_object")
        modes.append("prompt")
        return modes

    def _structured_request(
        self,
        resolved: ResolvedModel,
        messages: list[ChatMessage],
        mode: StructuredMode,
        schema: type[BaseModel],
        max_tokens: int | None,
    ) -> ChatRequest:
        response_format: dict[str, Any] | None = None
        if mode == "json_schema":
            response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": schema.__name__,
                    "schema": schema.model_json_schema(),
                    "strict": True,
                },
            }
        else:
            if mode == "json_object":
                response_format = {"type": "json_object"}
            instruction = self._prompts.render(
                "llm/structured_instruction",
                schema_json=json.dumps(schema.model_json_schema(), ensure_ascii=False),
            )
            messages = _with_instruction(messages, instruction.user)
        return self._request(
            resolved, messages, response_format=response_format, max_tokens=max_tokens
        )

    async def generate_structured[T: BaseModel](
        self,
        role: Role,
        prompt: PromptInput,
        schema: type[T],
        *,
        max_tokens: int | None = None,
    ) -> StructuredResult[T]:
        """スキーマに従う出力を生成し、Pydantic で検証して返す。

        サーバーがモードを拒否したら次のモードへ降格し、検証に失敗したらエラー内容を
        フィードバックして再試行する。上限を超えたら `StructuredOutputError`。
        """
        resolved = self._config.resolve(role)
        base_messages = _to_messages(prompt)
        modes = self.structured_modes(role)
        meter = _CallMeter()
        failures: list[str] = []
        mode_index = 0
        retries = 0
        messages = base_messages

        def record(success: bool, error: str | None = None) -> LLMCallRecord:
            return self._record(
                resolved,
                meter,
                prompt,
                kind="structured",
                schema_name=schema.__name__,
                structured_mode=modes[mode_index],
                success=success,
                retries=retries,
                error=error,
            )

        while True:
            mode = modes[mode_index]
            request = self._structured_request(resolved, messages, mode, schema, max_tokens)
            attempt = meter.new_attempt()
            try:
                raw = "".join([c.content async for c in self._chunks(resolved, request, attempt)])
            except LLMRequestRejectedError as e:
                failures.append(f"[{mode}] サーバーが拒否: {e}")
                if mode_index + 1 < len(modes):
                    mode_index += 1
                    messages = base_messages
                    continue
                record(False, failures[-1])
                raise StructuredOutputError(
                    "すべての構造化出力モードが拒否されました", failures
                ) from e
            except LLMError as e:
                record(False, str(e))
                raise

            try:
                value = schema.model_validate(extract_json(raw))
            except (ValueError, ValidationError) as e:
                failures.append(f"[{mode}] 検証失敗: {e}")
                if retries >= self._max_retries:
                    record(False, failures[-1])
                    raise StructuredOutputError(
                        f"構造化出力が {retries} 回の再試行後も検証を通りませんでした", failures
                    ) from e
                retries += 1
                messages = [
                    *messages,
                    ChatMessage(role="assistant", content=strip_reasoning(raw)),
                    ChatMessage(
                        role="user",
                        content=self._prompts.render(
                            "llm/structured_feedback", error=_truncate(str(e))
                        ).user,
                    ),
                ]
                continue

            return StructuredResult(value=value, raw_text=raw, record=record(True))
