"""LLM 呼び出しの計測記録。

1 回の論理呼び出し(構造化出力の再試行を含む)につき 1 件の `LLMCallRecord` を残す。
イベントログ(`LLMCallRecorded`)への変換はイベントストアを持つ engine 側で行う。
"""

import logging
import uuid
from datetime import datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

StructuredMode = Literal["json_schema", "json_object", "prompt"]


class LLMCallRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    call_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    started_at: datetime
    role: str
    model_key: str
    model: str
    provider: str
    kind: Literal["text", "structured"]
    prompt_name: str | None = None
    prompt_version: str | None = None
    schema_name: str | None = None
    structured_mode: StructuredMode | None = None
    """最後に使った構造化出力モード。"""
    ttft_ms: float | None = None
    """開始から最初のトークン(思考部分を含む)までの時間。"""
    total_ms: float
    input_tokens: int | None = None
    output_tokens: int | None = None
    tokens_per_s: float | None = None
    """出力トークン数 / 生成時間(初トークン以降)。"""
    success: bool
    attempts: int = 1
    retries: int = 0
    """検証失敗による再試行の回数(モード降格は含まない)。"""
    error: str | None = None
    messages: list[dict[str, str]] | None = None
    """最後の試行で送ったメッセージ(role, content)。入出力の記録が無効なら None。"""
    response_text: str | None = None
    """最後の試行の生の出力(本文)。"""
    reasoning_text: str | None = None
    """最後の試行の思考部分(サーバーが分けて返した分。長さに上限あり)。"""
    parsed: dict[str, Any] | None = None
    """構造化出力の検証済みの値。"""


class CallRecorder(Protocol):
    def record(self, record: LLMCallRecord) -> None: ...


class InMemoryRecorder:
    """記録をメモリに溜める。bench やテストで使う。"""

    def __init__(self) -> None:
        self.records: list[LLMCallRecord] = []

    def record(self, record: LLMCallRecord) -> None:
        self.records.append(record)
        logger.debug(
            "llm call role=%s model=%s success=%s total_ms=%.0f retries=%d",
            record.role,
            record.model,
            record.success,
            record.total_ms,
            record.retries,
        )
