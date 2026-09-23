"""ディベートの進行エンジン。

開廷 → 捜査 → 冒頭陳述 → 反論 × N → 最終弁論 → 判決 の順に進める。状態はイベントを
ストアに追記した結果としてのみ変わる(`DebateState.apply`)。
"""

import asyncio
import uuid
from collections.abc import Awaitable, Callable

from llm_court.agents.claim_extractor import ClaimExtractorAgent
from llm_court.agents.debater import DebaterAgent
from llm_court.agents.judge import JudgeAgent
from llm_court.config import Role
from llm_court.domain import (
    CitationIssuesDetected,
    Claim,
    ClaimsExtracted,
    DebatePhase,
    Event,
    EvidenceCollected,
    JudgeScored,
    LLMCallInfo,
    LLMCallRecorded,
    PhaseStarted,
    ResearchReport,
    SessionAborted,
    SessionStarted,
    Side,
    Statement,
    StatementMade,
    VerdictDelivered,
)
from llm_court.engine.citations import (
    check_citations,
    extract_citations,
)
from llm_court.engine.recorder import BufferedRecorder
from llm_court.engine.state import DebateState
from llm_court.engine.store import EventStore
from llm_court.llm import LLMClient, PromptLoader, StructuredOutputError
from llm_court.modes import DebateMode, Turn

ResearchFn = Callable[[str, Callable[[str], None]], Awaitable[ResearchReport]]


class DebateError(Exception):
    """ディベートを続行できない。"""


class DebateObserver:
    """進行の通知を受ける(CLI・API での表示用)。既定は何もしない。"""

    def on_event(self, event: Event) -> None:
        pass

    def on_progress(self, message: str) -> None:
        pass

    def on_statement_start(self, turn: Turn) -> None:
        pass

    def on_token(self, turn: Turn, chunk: str) -> None:
        pass


class DebateEngine:
    def __init__(
        self,
        *,
        llm: LLMClient,
        recorder: BufferedRecorder,
        prompts: PromptLoader,
        store: EventStore,
        mode: DebateMode,
        research: ResearchFn | None = None,
        observer: DebateObserver | None = None,
    ) -> None:
        self._llm = llm
        self._recorder = recorder
        self._store = store
        self._mode = mode
        self._research = research
        self._observer = observer or DebateObserver()
        self._debater = DebaterAgent(llm, prompts, mode)
        self._claim_extractor = ClaimExtractorAgent(llm, prompts)
        self._judge = JudgeAgent(llm, prompts, mode)
        self.session_id = ""
        self.state = DebateState()

    # --- イベント ---

    async def _emit(self, event: Event) -> Event:
        stored = await self._store.append(self.session_id, event)
        self.state = self.state.apply(stored)
        self._observer.on_event(stored)
        return stored

    async def _emit_calls(self, calls: list[LLMCallInfo]) -> None:
        for call in calls:
            await self._emit(
                LLMCallRecorded(
                    call=call, role=call.role, model=call.model, prompt_version=call.prompt_version
                )
            )

    async def _flush_llm_calls(self) -> None:
        await self._emit_calls(self._recorder.drain())

    def _model(self, role: Role) -> str:
        return self._llm.config.resolve(role).model.model

    # --- 進行 ---

    async def run(
        self, topic: str, rounds: int, *, evidence: ResearchReport | None = None
    ) -> DebateState:
        if rounds < 1:
            raise ValueError("rounds は 1 以上にしてください")
        if evidence is None and self._research is None:
            raise ValueError("証拠品も捜査手段も指定されていません")
        self.session_id = uuid.uuid4().hex[:12]
        self.state = DebateState()
        await self._emit(
            SessionStarted(
                topic=topic,
                mode=self._mode.name,
                rounds=rounds,
                models={
                    role.value: self._model(role)
                    for role in (Role.RESEARCHER, Role.DEBATER, Role.CLAIM_EXTRACTOR, Role.JUDGE)
                },
            )
        )
        try:
            await self._collect_evidence(topic, evidence)
            current: tuple[DebatePhase, int] | None = None
            for turn in self._mode.schedule(rounds):
                if current != (turn.phase, turn.round):
                    current = (turn.phase, turn.round)
                    await self._emit(PhaseStarted(phase=turn.phase, round=turn.round))
                await self._statement(topic, turn)
            await self._emit(PhaseStarted(phase=DebatePhase.VERDICT))
            await self._deliver_verdict(topic)
        except asyncio.CancelledError:
            await self._flush_llm_calls()
            await self._emit(SessionAborted(reason="中断されました"))
            raise
        except Exception as e:
            await self._flush_llm_calls()
            await self._emit(SessionAborted(reason=f"{type(e).__name__}: {e}"))
            raise
        return self.state

    async def _collect_evidence(self, topic: str, evidence: ResearchReport | None) -> None:
        role: str | None = None  # 既存の捜査結果を使う場合は LLM で生成していない
        if evidence is None:
            assert self._research is not None
            self._observer.on_progress("捜査を開始します")
            evidence = await self._research(topic, self._observer.on_progress)
            await self._flush_llm_calls()
            role = Role.RESEARCHER.value
        if not evidence.evidence:
            raise DebateError("証拠品が 1 件も集まりませんでした")
        await self._emit(EvidenceCollected(report=evidence, role=role))

    async def _statement(self, topic: str, turn: Turn) -> None:
        state = self.state
        prompt = self._debater.build_prompt(
            topic=topic,
            side=turn.side,
            phase=turn.phase,
            evidence=state.evidence,
            claims=state.claims,
            statements=state.statements,
        )
        self._observer.on_statement_start(turn)
        parts: list[str] = []
        async for chunk in self._debater.stream(prompt):
            parts.append(chunk)
            self._observer.on_token(turn, chunk)
        calls = self._recorder.drain()
        await self._emit_calls(calls)
        text = "".join(parts).strip()
        if not text:
            raise DebateError(f"{turn.side.label}の発言が空でした")

        number = len(state.statements) + 1
        statement = Statement(
            id=f"S-{number:02d}",
            side=turn.side,
            phase=turn.phase,
            round=turn.round,
            turn=number,
            text=text,
            cited_evidence_ids=extract_citations(text),
        )
        await self._emit(
            StatementMade(
                statement=statement,
                call_id=calls[-1].call_id if calls else None,
                role=Role.DEBATER.value,
                model=self._model(Role.DEBATER),
                prompt_version=prompt.version,
            )
        )
        issues = check_citations(statement.id, text, self.state.evidence_by_id)
        if issues:
            await self._emit(CitationIssuesDetected(statement_id=statement.id, issues=issues))
        await self._extract_claims(topic, statement)

    async def _extract_claims(self, topic: str, statement: Statement) -> None:
        try:
            result = await self._claim_extractor.extract(topic, statement)
        except StructuredOutputError:
            # 主張抽出の失敗は進行を止めない。失敗は LLMCallRecorded に残る
            await self._flush_llm_calls()
            return
        await self._flush_llm_calls()
        known = self.state.evidence_by_id
        offset = len(self.state.claims)
        claims = [
            Claim(
                id=f"C-{offset + i:02d}",
                statement_id=statement.id,
                side=statement.side,
                text=draft.text,
                kind=draft.kind,
                cited_evidence_ids=[
                    eid
                    for eid in extract_citations(
                        " ".join(f"[{x}]" for x in draft.cited_evidence_ids)
                    )
                    if eid in known
                ],
            )
            for i, draft in enumerate(result.value.claims, start=1)
        ]
        await self._emit(
            ClaimsExtracted(
                statement_id=statement.id,
                claims=claims,
                role=Role.CLAIM_EXTRACTOR.value,
                model=result.record.model,
                prompt_version=result.record.prompt_version,
            )
        )

    async def _deliver_verdict(self, topic: str) -> None:
        state = self.state
        self._observer.on_progress("裁判長が評議しています")
        orders = [[Side.AFFIRMATIVE, Side.NEGATIVE], [Side.NEGATIVE, Side.AFFIRMATIVE]]
        results = await asyncio.gather(
            *(
                self._judge.evaluate(
                    topic=topic,
                    order=order,
                    evidence=state.evidence,
                    statements=state.statements,
                    issues=state.citation_issues,
                )
                for order in orders
            )
        )
        await self._flush_llm_calls()
        for judged in results:
            await self._emit(
                JudgeScored(
                    score=judged.score,
                    role=Role.JUDGE.value,
                    model=judged.result.record.model,
                    prompt_version=judged.result.record.prompt_version,
                )
            )
        verdict = self._mode.decide([r.score for r in results])
        await self._emit(VerdictDelivered(verdict=verdict, role=Role.JUDGE.value))
