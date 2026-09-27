"""事前シミュレーション: 事件の起こりうる全行動に対する証人の応答を生成してパックにする。

- 行動は、分析官(`agents/trial_analyst.py`)が並べうるもの全部: 矛盾のある証言の
  全行 × 全証拠品の「つきつける」と、全行の「ゆさぶる」
- 応答は履歴なしで生成する(オフラインでは、どの順で選ばれても同じ応答を返すため)
- 各応答を逸脱の検査にかけ、逸脱があれば作り直して、逸脱の最も少ない応答を採用する
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from llm_court.agents.deviation import DeviationChecker
from llm_court.agents.trial_analyst import present_label, probe_label
from llm_court.agents.witness import WitnessAgent
from llm_court.config import Role
from llm_court.domain import Case, DeviationCheck, LLMCallInfo, Testimony, TrialOption
from llm_court.engine.explanation import build_explanation
from llm_court.llm import LLMClient, PromptLoader
from llm_court.modes import TrialMode
from llm_court.offline.models import (
    OfflineAnswers,
    OfflineContradiction,
    OfflineIndex,
    OfflineIndexItem,
    OfflineMeta,
    OfflineMode,
    OfflinePack,
    OfflineResponse,
    OfflineTrap,
    present_key,
    probe_key,
)

ProgressFn = Callable[[str], None]


@dataclass(frozen=True)
class Action:
    key: str
    testimony: Testimony
    option: TrialOption


def enumerate_actions(case: Case) -> list[Action]:
    """分析官が並べうる全行動(矛盾のある証言だけが尋問の対象になる)。"""
    evidence = {e.id: e for e in case.evidence}
    correct = {(c.testimony_line_id, c.evidence_id): c.id for c in case.contradictions}
    contradiction_lines = {c.testimony_line_id for c in case.contradictions}
    actions: list[Action] = []
    for testimony in case.testimonies:
        if not any(line.id in contradiction_lines for line in testimony.lines):
            continue
        for line in testimony.lines:
            actions.append(
                Action(
                    key=probe_key(line.id),
                    testimony=testimony,
                    option=TrialOption(
                        id=probe_key(line.id),
                        kind="probe",
                        line_id=line.id,
                        label=probe_label(line.text),
                    ),
                )
            )
            for ev in evidence.values():
                key = present_key(line.id, ev.id)
                contradiction_id = correct.get((line.id, ev.id))
                actions.append(
                    Action(
                        key=key,
                        testimony=testimony,
                        option=TrialOption(
                            id=key,
                            kind="present",
                            line_id=line.id,
                            evidence_id=ev.id,
                            label=present_label(line.text, ev.name),
                            contradiction_id=contradiction_id,
                        ),
                    )
                )
    return actions


def _deviation_count(check: DeviationCheck | None) -> int:
    return len(check.deviations) if check else 0


class OfflineSimulator:
    def __init__(
        self,
        *,
        llm: LLMClient,
        prompts: PromptLoader,
        mode: TrialMode,
        retries: int = 2,
        check_deviations: bool = True,
    ) -> None:
        self._llm = llm
        self._mode = mode
        self._retries = retries
        self._check = check_deviations
        self._witness = WitnessAgent(llm, prompts)
        self._checker = DeviationChecker(llm, prompts)
        self._prompt_versions: dict[str, str] = {}

    async def _respond(self, case: Case, action: Action) -> OfflineResponse:
        prompt = self._witness.build_prompt(
            case=case, testimony=action.testimony, option=action.option, history=[]
        )
        self._prompt_versions[prompt.name] = prompt.version
        should_collapse = action.option.contradiction_id is not None
        best: OfflineResponse | None = None
        attempts = 0
        for attempt in range(1, self._retries + 2):
            attempts = attempt
            result = await self._llm.generate_text(Role.WITNESS, prompt)
            text = result.text.strip()
            if not text:
                continue
            check = None
            if self._check:
                check = await self._checker.check(
                    case=case,
                    testimony=action.testimony,
                    option=action.option,
                    response=text,
                    should_collapse=should_collapse,
                )
            candidate = OfflineResponse(
                key=action.key,
                witness_id=action.testimony.witness_id,
                text=text,
                should_collapse=should_collapse,
                check=check,
                attempts=attempt,
                call=LLMCallInfo.model_validate(result.record.model_dump()),
            )
            if best is None or _deviation_count(check) < _deviation_count(best.check):
                best = candidate
            if _deviation_count(check) == 0:
                break
        if best is None:
            raise RuntimeError(f"証人の応答が空でした({action.key})")
        return best.model_copy(update={"attempts": attempts})

    async def build(self, case: Case, on_progress: ProgressFn | None = None) -> OfflinePack:
        actions = enumerate_actions(case)
        done = 0

        async def run(action: Action) -> OfflineResponse:
            nonlocal done
            response = await self._respond(case, action)
            done += 1
            if on_progress is not None:
                on_progress(f"{case.id}: 証人の応答 {done}/{len(actions)}")
            return response

        # 並列度は LLM 層のプロバイダごとのセマフォで制限される
        responses = list(await asyncio.gather(*(run(a) for a in actions)))
        mode = self._mode
        models = {Role.WITNESS.value: self._llm.config.resolve(Role.WITNESS).model.model}
        if self._check:
            models[Role.JUDGE.value] = self._llm.config.resolve(Role.JUDGE).model.model
        return OfflinePack(
            case=case.public_view(),
            theme=case.theme,
            answers=OfflineAnswers(
                contradictions=[
                    OfflineContradiction(
                        id=c.id,
                        testimony_line_id=c.testimony_line_id,
                        evidence_id=c.evidence_id,
                        traps=[
                            OfflineTrap(evidence_id=t.evidence_id, why_tempting=t.why_tempting)
                            for t in c.traps
                        ],
                    )
                    for c in case.contradictions
                ],
                answer_index=case.question.answer_index,
            ),
            explanation=build_explanation(case),
            mode=OfflineMode(
                penalty_gauge=mode.penalty_gauge,
                penalties=mode.penalties,
                distractor_options=mode.distractor_options,
                probe_options=mode.probe_options,
            ),
            responses=responses,
            meta=OfflineMeta(
                generated_at=datetime.now(UTC),
                models=models,
                prompt_versions=dict(self._prompt_versions),
                responses=len(responses),
                deviations=sum(_deviation_count(r.check) > 0 for r in responses),
                unchecked=sum(r.check is None for r in responses) if self._check else 0,
            ),
        )


def build_index(packs: list[OfflinePack]) -> OfflineIndex:
    return OfflineIndex(
        cases=[
            OfflineIndexItem(
                id=p.case.id,
                title=p.case.title,
                theme=p.theme,
                overview=p.case.overview,
                testimonies=len(p.case.testimonies),
                contradictions=len(p.answers.contradictions),
                responses=len(p.responses),
                generated_at=p.meta.generated_at,
            )
            for p in sorted(packs, key=lambda p: p.meta.generated_at)
        ]
    )
