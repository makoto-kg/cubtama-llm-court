"""未選択の選択肢の強さを、プレイヤー向けの出力で伏せる。

ストアには完全な形で保存し(真実はイベントログ)、API のレスポンス・イベント一覧・SSE でだけ伏せる。
選択後は伏せない(`ChoiceMade` で選んだ候補の強さが公開される)。
"""

from collections.abc import Sequence

from llm_court.domain import ChoiceMade, ChoicesPrepared, Event


def redact_choices(event: ChoicesPrepared) -> ChoicesPrepared:
    return event.model_copy(update={"options": [o.redacted() for o in event.options]})


def redact_live(event: Event) -> Event:
    """発生した直後のイベント(選択肢は必ず未選択)。"""
    return redact_choices(event) if isinstance(event, ChoicesPrepared) else event


def redact_events(events: Sequence[Event]) -> list[Event]:
    """イベント列のうち、その後に選択(`ChoiceMade`)がない選択肢だけを伏せる。"""
    result: list[Event] = []
    for i, event in enumerate(events):
        if isinstance(event, ChoicesPrepared) and not any(
            isinstance(e, ChoiceMade) for e in events[i + 1 :]
        ):
            event = redact_choices(event)
        result.append(event)
    return result
