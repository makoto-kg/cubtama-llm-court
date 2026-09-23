"""LLM 呼び出しの記録を溜め、イベントとして追記できるようにする。"""

from llm_court.domain import LLMCallInfo
from llm_court.llm import LLMCallRecord


class BufferedRecorder:
    """`CallRecorder` の実装。エンジンがステップごとに `drain` して `LLMCallRecorded` にする。"""

    def __init__(self) -> None:
        self._pending: list[LLMCallRecord] = []

    def record(self, record: LLMCallRecord) -> None:
        self._pending.append(record)

    def drain(self) -> list[LLMCallInfo]:
        pending, self._pending = self._pending, []
        return [LLMCallInfo.model_validate(r.model_dump()) for r in pending]
