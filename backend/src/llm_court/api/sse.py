"""SSE(Server-Sent Events)のストリーム生成。"""

import asyncio
import json
from collections.abc import AsyncGenerator

from llm_court.api.hub import SessionHub, StreamMessage
from llm_court.api.redaction import redact_events
from llm_court.domain import Event, SessionAborted, TrialFinished, VerdictDelivered
from llm_court.engine.store import EventStore


def format_sse(message: StreamMessage) -> str:
    lines: list[str] = []
    if message.id is not None:
        lines.append(f"id: {message.id}")
    lines.append(f"event: {message.event}")
    lines.append(f"data: {json.dumps(message.data, ensure_ascii=False)}")
    return "\n".join(lines) + "\n\n"


def debate_message(event: Event) -> StreamMessage:
    return StreamMessage(event="debate", data=event.model_dump(mode="json"), id=event.seq)


def is_terminal(event: Event) -> bool:
    return isinstance(event, VerdictDelivered | SessionAborted | TrialFinished)


async def session_stream(
    *,
    session_id: str,
    after: int,
    store: EventStore,
    hub: SessionHub,
    keepalive_s: float,
) -> AsyncGenerator[str]:
    """`after` より後の履歴を送り、続けて新着を送る。判決・閉廷・中断を送ったら終わる。

    購読を先に始めてから履歴を読むので、その間に追記されたイベントも取りこぼさない
    (seq で重複を除く)。
    """
    with hub.subscribe(session_id) as queue:
        last = after
        for event in redact_events(await store.load(session_id)):
            if event.seq <= last:
                if is_terminal(event):
                    return  # 終端まで受信済み
                continue
            last = event.seq
            yield format_sse(debate_message(event))
            if is_terminal(event):
                return
        while True:
            try:
                message = await asyncio.wait_for(queue.get(), timeout=keepalive_s)
            except TimeoutError:
                yield ": keepalive\n\n"
                continue
            if message.event == "debate":
                assert message.id is not None
                if message.id <= last:
                    continue
                last = message.id
            yield format_sse(message)
            if message.event == "debate" and message.data.get("type") in (
                "verdict_delivered",
                "session_aborted",
                "trial_finished",
            ):
                return
