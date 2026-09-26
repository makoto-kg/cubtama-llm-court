"""LLM 呼び出しの記録を溜め、イベントとして追記できるようにする。"""

from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar

from llm_court.domain import LLMCallInfo
from llm_court.llm import LLMCallRecord


class BufferedRecorder:
    """`CallRecorder` の実装。エンジンがステップごとに `drain` して `LLMCallRecorded` にする。

    1 つの LLMClient を複数のセッションで共有する場合(API)は、セッションの処理を
    `isolated()` の中で実行すると、記録がそのタスク(と子タスク)ごとに分かれる。
    """

    def __init__(self) -> None:
        self._shared: list[LLMCallRecord] = []
        self._current: ContextVar[list[LLMCallRecord] | None] = ContextVar(
            f"llm_call_buffer_{id(self)}", default=None
        )

    def _buffer(self) -> list[LLMCallRecord]:
        buffer = self._current.get()
        return self._shared if buffer is None else buffer

    def record(self, record: LLMCallRecord) -> None:
        self._buffer().append(record)

    def drain(self) -> list[LLMCallInfo]:
        buffer = self._buffer()
        pending = list(buffer)
        buffer.clear()
        return [LLMCallInfo.model_validate(r.model_dump()) for r in pending]

    @contextmanager
    def isolated(self) -> Generator[None]:
        """この中の記録(ここから作られる子タスクを含む)を専用のバッファに溜める。"""
        token = self._current.set([])
        try:
            yield
        finally:
            self._current.reset(token)
