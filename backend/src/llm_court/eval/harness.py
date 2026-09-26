"""評価ハーネス: 構成ごとにディベートを実行し、裁判長の再評価・参照評価を行う。"""

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from llm_court.agents.judge import JudgeAgent
from llm_court.config import ModelsConfig, Role, load_models_config
from llm_court.domain import LLMCallInfo, ResearchReport, Side
from llm_court.engine.debate import DebateEngine
from llm_court.engine.recorder import BufferedRecorder
from llm_court.engine.state import DebateState
from llm_court.engine.store import EventStore, export_jsonl
from llm_court.eval.models import DebateRun, EvalResult, Judging, JudgingSource
from llm_court.eval.spec import EvalSpec
from llm_court.llm import LLMClient, LLMConnectionError, LLMError, PromptLoader
from llm_court.modes import DebateMode

logger = logging.getLogger(__name__)

ClientFactory = Callable[[ModelsConfig, BufferedRecorder], LLMClient]
ProgressFn = Callable[[str], None]

_ORDERS = ([Side.AFFIRMATIVE, Side.NEGATIVE], [Side.NEGATIVE, Side.AFFIRMATIVE])


class EvalHarness:
    def __init__(
        self,
        *,
        prompts: PromptLoader,
        mode: DebateMode,
        client_factory: ClientFactory,
        out_dir: Path,
    ) -> None:
        self._prompts = prompts
        self._mode = mode
        self._client_factory = client_factory
        self._out_dir = out_dir

    async def run(self, spec: EvalSpec, on_progress: ProgressFn | None = None) -> EvalResult:
        def progress(message: str) -> None:
            logger.debug(message)
            if on_progress is not None:
                on_progress(message)

        started_at = datetime.now(UTC)
        reports = {
            t.topic: ResearchReport.model_validate_json(t.evidence.read_text(encoding="utf-8"))
            for t in spec.topics
        }
        self._out_dir.mkdir(parents=True, exist_ok=True)
        store = await EventStore.open(self._out_dir / "events.db")

        reference: tuple[LLMClient, BufferedRecorder] | None = None
        if spec.reference_judge is not None:
            ref_recorder = BufferedRecorder()
            reference = (
                self._client_factory(load_models_config(spec.reference_judge), ref_recorder),
                ref_recorder,
            )

        runs: list[DebateRun] = []
        configs: dict[str, dict[str, str]] = {}
        total = len(spec.configs) * len(spec.topics) * spec.runs
        try:
            for config in spec.configs:
                models = load_models_config(config.models)
                configs[config.name] = {r.value: models.resolve(r).model.model for r in Role}
                recorder = BufferedRecorder()
                async with self._client_factory(models, recorder) as client:
                    for topic in spec.topics:
                        for n in range(1, spec.runs + 1):
                            progress(
                                f"[{len(runs) + 1}/{total}] {config.name}: {topic.topic}({n} 回目)"
                            )
                            runs.append(
                                await self._debate(
                                    spec,
                                    config.name,
                                    client,
                                    recorder,
                                    store,
                                    topic.topic,
                                    reports[topic.topic],
                                    n,
                                    reference,
                                    progress,
                                )
                            )
        finally:
            await store.aclose()
            if reference is not None:
                await reference[0].aclose()

        return EvalResult(
            name=spec.name,
            started_at=started_at,
            finished_at=datetime.now(UTC),
            rounds=spec.rounds,
            judge_repeats=spec.judge_repeats,
            configs=configs,
            reference_judge=(
                reference[0].config.resolve(Role.JUDGE).model.model if reference else None
            ),
            runs=runs,
        )

    async def _debate(
        self,
        spec: EvalSpec,
        config: str,
        client: LLMClient,
        recorder: BufferedRecorder,
        store: EventStore,
        topic: str,
        report: ResearchReport,
        n: int,
        reference: tuple[LLMClient, BufferedRecorder] | None,
        progress: ProgressFn,
    ) -> DebateRun:
        engine = DebateEngine(
            llm=client, recorder=recorder, prompts=self._prompts, store=store, mode=self._mode
        )
        error: str | None = None
        try:
            await engine.run(topic, spec.rounds, evidence=report)
        except LLMConnectionError:
            raise
        except Exception as e:
            # 1 回の失敗は記録して続ける(中断率も指標に含める)
            error = f"{type(e).__name__}: {e}"
            logger.warning("ディベートが中断しました(%s / %s): %s", config, topic, error)
        events = await store.load(engine.session_id)
        export_jsonl(events, self._out_dir / "debates" / f"{config}-{engine.session_id}.jsonl")
        state = DebateState.from_events(events)

        judgings: list[Judging] = []
        judge_calls: list[LLMCallInfo] = []
        if state.verdict is not None:
            judgings.append(
                Judging(source="debate", scores=state.judge_scores, verdict=state.verdict)
            )
            judge = JudgeAgent(client, self._prompts, self._mode)
            for k in range(1, spec.judge_repeats + 1):
                progress(f"裁判長の再評価 {k}/{spec.judge_repeats}")
                judging = await self._judge(judge, state, "repeat", k)
                if judging is not None:
                    judgings.append(judging)
            judge_calls += recorder.drain()
            if reference is not None:
                progress("参照用裁判長の評価")
                ref_client, ref_recorder = reference
                ref_judge = JudgeAgent(ref_client, self._prompts, self._mode)
                judging = await self._judge(ref_judge, state, "reference", 0)
                if judging is not None:
                    judgings.append(judging)
                judge_calls += ref_recorder.drain()

        return DebateRun(
            config=config,
            topic=topic,
            run=n,
            session_id=engine.session_id,
            events=events,
            judgings=judgings,
            judge_calls=judge_calls,
            error=error,
        )

    async def _judge(
        self, judge: JudgeAgent, state: DebateState, source: JudgingSource, repeat: int
    ) -> Judging | None:
        """2 つの提示順で評価して判決を決める。失敗したら None(失敗は計測記録に残る)。"""
        assert state.topic is not None
        try:
            results = await asyncio.gather(
                *(
                    judge.evaluate(
                        topic=state.topic,
                        order=order,
                        evidence=state.evidence,
                        statements=state.statements,
                        issues=state.citation_issues,
                    )
                    for order in _ORDERS
                )
            )
        except LLMConnectionError:
            raise
        except LLMError as e:
            logger.warning("裁判長の評価に失敗しました(%s %d): %s", source, repeat, e)
            return None
        scores = [r.score for r in results]
        return Judging(
            source=source, repeat=repeat, scores=scores, verdict=self._mode.decide(scores)
        )
