"""未選択の選択肢の強さを、プレイヤー向けの出力で伏せる。

ストアには完全な形で保存し(真実はイベントログ)、API のレスポンス・イベント一覧・SSE でだけ伏せる。
選択後は伏せない(`ChoiceMade` で選んだ候補の強さが公開される)。

分析官の LLM 呼び出しの記録(思考ログ)も、生出力・思考部分・パース結果に強さを含むため、
その選択肢が選ばれるまで伏せる。
"""

from collections.abc import Sequence

from llm_court.config import Role
from llm_court.domain import ChoiceMade, ChoicesPrepared, Event, LLMCallRecorded


def redact_choices(event: ChoicesPrepared) -> ChoicesPrepared:
    return event.model_copy(update={"options": [o.redacted() for o in event.options]})


def _is_analyst_call(event: Event) -> bool:
    return isinstance(event, LLMCallRecorded) and event.call.role == Role.ANALYST.value


def redact_call(event: LLMCallRecorded) -> LLMCallRecorded:
    call = event.call.model_copy(
        update={"response_text": None, "reasoning_text": None, "parsed": None}
    )
    return event.model_copy(update={"call": call})


def redact_live(event: Event) -> Event:
    """発生した直後のイベント(選択肢は必ず未選択)。"""
    if isinstance(event, ChoicesPrepared):
        return redact_choices(event)
    if isinstance(event, LLMCallRecorded) and _is_analyst_call(event):
        return redact_call(event)
    return event


def redact_events(events: Sequence[Event]) -> list[Event]:
    """未選択の選択肢と、それを作った分析官の呼び出しの出力だけを伏せる。"""
    pending = next(
        (
            i
            for i in range(len(events) - 1, -1, -1)
            if isinstance(events[i], ChoicesPrepared)
            and not any(isinstance(e, ChoiceMade) for e in events[i + 1 :])
        ),
        None,
    )
    if pending is None:
        return list(events)
    # 直前の選択以降の分析官の呼び出しが、未選択の選択肢を作ったもの
    since = max(
        (i for i, e in enumerate(events[:pending]) if isinstance(e, ChoiceMade)), default=-1
    )
    result: list[Event] = []
    for i, event in enumerate(events):
        if i == pending and isinstance(event, ChoicesPrepared):
            event = redact_choices(event)
        elif since < i < pending and isinstance(event, LLMCallRecorded) and _is_analyst_call(event):
            event = redact_call(event)
        result.append(event)
    return result
