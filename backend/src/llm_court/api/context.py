"""API が共有する資源(ストア、LLM クライアント、捜査パイプライン、配信、タスク)。"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from llm_court.api.hub import SessionHub, StreamMessage
from llm_court.api.redaction import redact_live, redact_trial_event
from llm_court.api.tasks import TaskRunner
from llm_court.config import Settings
from llm_court.domain import Event, ResearchReport
from llm_court.engine.debate import DebateEngine, DebateObserver
from llm_court.engine.recorder import BufferedRecorder
from llm_court.engine.store import EventStore
from llm_court.engine.trial import TrialEngine, TrialObserver
from llm_court.llm import LLMClient, PromptLoader
from llm_court.modes import DebateMode, TrialMode, Turn
from llm_court.scenario.store import CaseStore


class HubObserver(DebateObserver):
    """エンジンの通知を SSE の購読者に配信する。"""

    def __init__(self, hub: SessionHub, engine_session: "DebateEngine") -> None:
        self._hub = hub
        self._engine = engine_session

    def _publish(self, message: StreamMessage) -> None:
        self._hub.publish(self._engine.session_id, message)

    def on_event(self, event: Event) -> None:
        event = redact_live(event)
        self._publish(
            StreamMessage(event="debate", data=event.model_dump(mode="json"), id=event.seq)
        )

    def on_progress(self, message: str) -> None:
        self._publish(StreamMessage(event="progress", data={"message": message}))

    def on_statement_start(self, turn: Turn) -> None:
        self._publish(StreamMessage(event="turn", data=turn.model_dump(mode="json")))

    def on_token(self, turn: Turn, chunk: str) -> None:
        self._publish(
            StreamMessage(event="token", data={**turn.model_dump(mode="json"), "text": chunk})
        )


class TrialHubObserver(TrialObserver):
    """裁判のエンジンの通知を SSE の購読者に配信する(閉廷前の非公開の情報は伏せる)。"""

    def __init__(self, hub: SessionHub, engine: TrialEngine) -> None:
        self._hub = hub
        self._engine = engine

    def _publish(self, message: StreamMessage) -> None:
        self._hub.publish(self._engine.session_id, message)

    def on_event(self, event: Event) -> None:
        event = redact_trial_event(event)
        self._publish(
            StreamMessage(event="debate", data=event.model_dump(mode="json"), id=event.seq)
        )

    def on_progress(self, message: str) -> None:
        self._publish(StreamMessage(event="progress", data={"message": message}))

    def on_witness_start(self, witness_id: str) -> None:
        self._publish(StreamMessage(event="witness", data={"witness_id": witness_id}))

    def on_witness_token(self, witness_id: str, chunk: str) -> None:
        self._publish(StreamMessage(event="token", data={"witness_id": witness_id, "text": chunk}))


class Researcher(Protocol):
    """捜査の実行者(`ResearchPipeline` が満たす)。"""

    async def run(
        self, topic: str, on_progress: Callable[[str], None] | None = None
    ) -> ResearchReport: ...


@dataclass
class ApiContext:
    settings: Settings
    store: EventStore
    llm: LLMClient
    recorder: BufferedRecorder
    prompts: PromptLoader
    mode: DebateMode
    research: Researcher
    hub: SessionHub
    tasks: TaskRunner
    trial_mode: TrialMode
    cases: CaseStore

    def engine(self) -> DebateEngine:
        engine = DebateEngine(
            llm=self.llm,
            recorder=self.recorder,
            prompts=self.prompts,
            store=self.store,
            mode=self.mode,
            research=self.research.run,
        )
        engine.set_observer(HubObserver(self.hub, engine))
        return engine

    def trial_engine(self) -> TrialEngine:
        engine = TrialEngine(
            llm=self.llm,
            recorder=self.recorder,
            prompts=self.prompts,
            store=self.store,
            mode=self.trial_mode,
        )
        engine.set_observer(TrialHubObserver(self.hub, engine))
        return engine
