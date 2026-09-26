"""ディベートの進行エンジン。

開廷 → 捜査 → 冒頭陳述 → 反論 × N → 最終弁論 → 判決 の順に進める。状態はイベントを
ストアに追記した結果としてのみ変わる(`DebateState.apply`)。
"""

import asyncio
import uuid
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Literal

from llm_court.agents.advocate import AdvocateAgent
from llm_court.agents.analyst import AnalystAgent
from llm_court.agents.claim_extractor import ClaimExtractorAgent
from llm_court.agents.debater import DebaterAgent
from llm_court.agents.judge import JudgeAgent
from llm_court.config import Role
from llm_court.domain import (
    ChoiceMade,
    ChoiceOption,
    ChoicesPrepared,
    CitationIssuesDetected,
    Claim,
    ClaimsExtracted,
    DebatePhase,
    Event,
    EvidenceCollected,
    JudgeScored,
    LLMCallInfo,
    LLMCallRecorded,
    PenaltyApplied,
    PhaseStarted,
    ResearchReport,
    SessionAborted,
    SessionStarted,
    Side,
    Statement,
    StatementMade,
    Verdict,
    VerdictDelivered,
)
from llm_court.engine.citations import (
    check_citations,
    extract_citations,
)
from llm_court.engine.recorder import BufferedRecorder
from llm_court.engine.state import DebateState
from llm_court.engine.store import EventStore
from llm_court.llm import LLMClient, PromptLoader, RenderedPrompt, StructuredOutputError
from llm_court.modes import DebateMode, Turn

ResearchFn = Callable[[str, Callable[[str], None]], Awaitable[ResearchReport]]


class DebateError(Exception):
    """ディベートを続行できない。"""


class SessionStateError(DebateError):
    """現在の状態ではその操作をできない(手順違反)。セッションは中断しない。"""


class InvalidChoiceError(DebateError):
    """示されていない選択肢が指定された。"""


class SessionNotFoundError(DebateError):
    """指定したセッションがない。"""


Step = Turn | Literal["verdict"]


def next_step(state: DebateState, mode: DebateMode) -> Step | None:
    """状態から次の手番を決める。証拠品がない・閉廷している場合は None。"""
    if state.finished or state.research is None:
        return None
    schedule = mode.schedule(state.rounds)
    done = len(state.statements)
    return schedule[done] if done < len(schedule) else "verdict"


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
        self._analyst = AnalystAgent(llm, prompts, mode)
        self._advocate = AdvocateAgent(llm, prompts, mode)
        self.session_id = ""
        self.state = DebateState()

    def set_observer(self, observer: DebateObserver) -> None:
        self._observer = observer

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

    async def start(self, topic: str, rounds: int, *, human_side: Side | None = None) -> str:
        """開廷する(`SessionStarted` を記録する)。セッション ID を返す。

        `human_side` を指定すると、その陣営は人間が選択肢を選んで進める。
        """
        if rounds < 1:
            raise ValueError("rounds は 1 以上にしてください")
        roles = [Role.RESEARCHER, Role.DEBATER, Role.CLAIM_EXTRACTOR, Role.JUDGE]
        if human_side is not None:
            roles += [Role.ANALYST, Role.ADVOCATE]
        self.session_id = uuid.uuid4().hex[:12]
        self.state = DebateState()
        await self._emit(
            SessionStarted(
                topic=topic,
                mode=self._mode.name,
                rounds=rounds,
                models={role.value: self._model(role) for role in roles},
                human_side=human_side,
                penalty_gauge=self._mode.penalty_gauge if human_side is not None else 0,
            )
        )
        return self.session_id

    async def resume(self, session_id: str) -> DebateState:
        """イベントストアから状態を再構築して、続きを進められるようにする。"""
        events = await self._store.load(session_id)
        if not events:
            raise SessionNotFoundError(session_id)
        self.session_id = session_id
        self.state = DebateState.from_events(events)
        return self.state

    async def collect_evidence(self, evidence: ResearchReport | None = None) -> None:
        """証拠品をそろえる。`evidence` がなければ捜査する。"""
        state = self.state
        if state.session_id is None or state.topic is None:
            raise SessionStateError("開廷していません")
        if state.finished:
            raise SessionStateError("閉廷しています")
        if state.research is not None:
            raise SessionStateError("証拠品はすでに集まっています")
        if evidence is None and self._research is None:
            raise SessionStateError("証拠品も捜査手段も指定されていません")
        async with self._abort_on_error():
            await self._collect_evidence(state.topic, evidence)

    async def advance(self) -> Step:
        """次の 1 手(発言または判決)を進め、進めた手を返す。"""
        step = next_step(self.state, self._mode)
        if step is None:
            if self.state.research is None and not self.state.finished:
                raise SessionStateError("証拠品がまだありません")
            raise SessionStateError("これ以上進める手番がありません")
        assert self.state.topic is not None
        topic = self.state.topic
        if self.is_human_turn(step) and self.state.pending_choices is not None:
            raise SessionStateError("人間の選択待ちです。選択肢から選んでください")
        async with self._abort_on_error():
            if step == "verdict":
                if self.state.phase is not DebatePhase.VERDICT:
                    await self._emit(PhaseStarted(phase=DebatePhase.VERDICT))
                await self._deliver_verdict(topic)
            elif self.is_human_turn(step):
                await self._enter_turn(step)
                await self._prepare_choices(topic, step)
            else:
                await self._enter_turn(step)
                await self._llm_statement(topic, step)
                # 先行実行: 次が人間の手番なら、相手の発言が終わった時点で選択肢を用意する
                following = next_step(self.state, self._mode)
                if isinstance(following, Turn) and self.is_human_turn(following):
                    await self._enter_turn(following)
                    await self._prepare_choices(topic, following)
        return step

    async def run_to_end(self) -> DebateState:
        """判決まで進める。人間の手番では選択肢を用意して止まる。"""
        while (step := next_step(self.state, self._mode)) is not None:
            if self.is_human_turn(step):
                if self.state.pending_choices is None:
                    await self.advance()
                break
            await self.advance()
        return self.state

    def is_human_turn(self, step: Step | None) -> bool:
        return isinstance(step, Turn) and step.side is self.state.human_side

    async def choose(self, option_id: str) -> None:
        """人間が選んだ選択肢で手番を進める(ペナルティの適用と、代弁者による清書)。"""
        step = next_step(self.state, self._mode)
        pending = self.state.pending_choices
        if not isinstance(step, Turn) or not self.is_human_turn(step) or pending is None:
            raise SessionStateError("人間の選択を受け付ける手番ではありません")
        option = next((o for o in pending.options if o.id == option_id), None)
        if option is None:
            raise InvalidChoiceError(f"選択肢 {option_id} はありません")
        assert self.state.topic is not None
        topic = self.state.topic
        async with self._abort_on_error():
            await self._emit(ChoiceMade(option=option))
            penalty = self._mode.penalty_for(option.strength)
            if penalty:
                remaining = self.state.penalty_gauge - penalty
                await self._emit(
                    PenaltyApplied(
                        amount=penalty,
                        remaining=remaining,
                        reason=f"{option.strength} の指摘を選んだ",
                    )
                )
                if remaining <= 0:
                    await self._lose_by_penalty(step.side)
                    return
            await self._advocate_statement(topic, step, option)

    async def _enter_turn(self, turn: Turn) -> None:
        if (self.state.phase, self.state.round) != (turn.phase, turn.round):
            await self._emit(PhaseStarted(phase=turn.phase, round=turn.round))

    async def _prepare_choices(self, topic: str, turn: Turn) -> None:
        state = self.state
        self._observer.on_progress("分析官が選択肢を用意しています")
        number = len(state.statements) + 1
        prepared = await self._analyst.prepare(
            topic=topic,
            side=turn.side,
            phase=turn.phase,
            evidence=state.evidence,
            claims=state.claims,
            statements=state.statements,
            issues=state.citation_issues,
            id_prefix=f"T{number:02d}",
            seed=f"{self.session_id}-{number}",
        )
        await self._flush_llm_calls()
        await self._emit(
            ChoicesPrepared(
                phase=turn.phase,
                round=turn.round,
                side=turn.side,
                options=prepared.options,
                discarded=prepared.discarded,
                role=Role.ANALYST.value,
                model=self._model(Role.ANALYST),
                prompt_version=prepared.prompt_version,
            )
        )

    async def _lose_by_penalty(self, human: Side) -> None:
        await self._emit(PhaseStarted(phase=DebatePhase.VERDICT))
        await self._emit(
            VerdictDelivered(
                verdict=Verdict(
                    winner=human.opponent,
                    agreed=True,
                    totals=dict.fromkeys(Side, 0.0),
                    rationale=f"{human.label}のペナルティゲージが尽きたため、{human.opponent.label}の勝ちとします。",
                    decided_by="penalty",
                )
            )
        )

    async def run(
        self, topic: str, rounds: int, *, evidence: ResearchReport | None = None
    ) -> DebateState:
        """開廷から判決まで一度に進める(CLI・評価ハーネス用)。"""
        if evidence is None and self._research is None:
            raise ValueError("証拠品も捜査手段も指定されていません")
        await self.start(topic, rounds)
        await self.collect_evidence(evidence)
        return await self.run_to_end()

    @asynccontextmanager
    async def _abort_on_error(self) -> AsyncGenerator[None]:
        """処理中の例外は `SessionAborted` として記録してから送出する。"""
        try:
            yield
        except asyncio.CancelledError:
            await self._flush_llm_calls()
            await self._emit(SessionAborted(reason="中断されました"))
            raise
        except Exception as e:
            await self._flush_llm_calls()
            await self._emit(SessionAborted(reason=f"{type(e).__name__}: {e}"))
            raise

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

    async def _llm_statement(self, topic: str, turn: Turn) -> None:
        state = self.state
        prompt = self._debater.build_prompt(
            topic=topic,
            side=turn.side,
            phase=turn.phase,
            evidence=state.evidence,
            claims=state.claims,
            statements=state.statements,
        )
        await self._statement(topic, turn, prompt, self._debater.stream(prompt), Role.DEBATER)

    async def _advocate_statement(self, topic: str, turn: Turn, option: ChoiceOption) -> None:
        state = self.state
        prompt = self._advocate.build_prompt(
            topic=topic,
            side=turn.side,
            phase=turn.phase,
            option=option,
            evidence=state.evidence,
            claims=state.claims,
            statements=state.statements,
        )
        await self._statement(topic, turn, prompt, self._advocate.stream(prompt), Role.ADVOCATE)

    async def _statement(
        self,
        topic: str,
        turn: Turn,
        prompt: RenderedPrompt,
        chunks: AsyncIterator[str],
        role: Role,
    ) -> None:
        state = self.state
        self._observer.on_statement_start(turn)
        parts: list[str] = []
        async for chunk in chunks:
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
                role=role.value,
                model=self._model(role),
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
