"""未選択の選択肢の強さを、プレイヤー向けの出力で伏せる。

ストアには完全な形で保存し(真実はイベントログ)、API のレスポンス・イベント一覧・SSE でだけ伏せる。
選択後は伏せない(`ChoiceMade` で選んだ候補の強さが公開される)。

分析官の LLM 呼び出しの記録(思考ログ)も、生出力・思考部分・パース結果に強さを含むため、
その選択肢が選ばれるまで伏せる。
"""

from collections.abc import Sequence

from llm_court.config import Role
from llm_court.domain import (
    Case,
    CaseQuestion,
    ChoiceMade,
    ChoicesPrepared,
    Event,
    HiddenTruth,
    LLMCallRecorded,
    SessionAborted,
    Testimony,
    TrialChoicesPrepared,
    TrialFinished,
    TrialStarted,
)


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
    """未選択の選択肢と、それを作った分析官の呼び出しの出力だけを伏せる。

    裁判のセッションは `redact_trial_events` の規則で伏せる。
    """
    if events and isinstance(events[0], TrialStarted):
        return redact_trial_events(events)
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


# --- 裁判型 ---
#
# 閉廷までは、事件の非公開の情報(真相・台本・矛盾・正解・学習ポイント)と、それを含む
# LLM 呼び出しの入出力、並べた選択肢の強さを伏せる。過去に並べた選択肢も伏せるのは、
# 選ばれなかった正解の組が、次の尋問で再び並ぶため。閉廷後(中断を含む)はすべて公開する。


def redact_case(case: Case) -> Case:
    """公開の情報だけを残した事件(型を保つため `Case` のまま、非公開の欄を空にする)。"""
    return case.model_copy(
        update={
            "learning_points": [],
            "hidden_truth": HiddenTruth(summary="", timeline=[], lies=[]),
            "witness_scripts": [],
            "contradictions": [],
            "question": CaseQuestion.model_construct(
                text=case.question.text, options=case.question.options, answer_index=-1
            ),
            "testimonies": [
                Testimony(
                    id=t.id,
                    witness_id=t.witness_id,
                    title=t.title,
                    lines=[line.model_copy(update={"lie_id": None}) for line in t.lines],
                )
                for t in case.testimonies
            ],
            "generation": None,
            "validation": None,
        }
    )


def redact_trial_call(event: LLMCallRecorded) -> LLMCallRecorded:
    call = event.call.model_copy(
        update={"messages": None, "response_text": None, "reasoning_text": None, "parsed": None}
    )
    return event.model_copy(update={"call": call})


def redact_trial_event(event: Event) -> Event:
    """閉廷前の裁判のイベントを伏せる(SSE で発生直後に送るときもこれを使う)。"""
    match event:
        case TrialStarted():
            return event.model_copy(update={"case": redact_case(event.case)})
        case TrialChoicesPrepared():
            return event.model_copy(update={"options": [o.redacted() for o in event.options]})
        case LLMCallRecorded():
            return redact_trial_call(event)
        case _:
            return event


def redact_trial_events(events: Sequence[Event]) -> list[Event]:
    if any(isinstance(e, TrialFinished | SessionAborted) for e in events):
        return list(events)
    return [redact_trial_event(e) for e in events]
