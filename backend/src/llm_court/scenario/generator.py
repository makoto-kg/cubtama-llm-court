"""事件の段階的な生成と検証(作り直しを含む)。"""

import logging
import uuid
from collections import Counter
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel

from llm_court.config import Role, ScenarioSettings
from llm_court.domain import (
    Case,
    CaseGeneration,
    Contradiction,
    Evidence,
    HiddenTruth,
    LearningPoint,
    Person,
    ResearchReport,
)
from llm_court.llm import InMemoryRecorder, LLMClient, PromptLoader, RenderedPrompt
from llm_court.modes import TrialMode
from llm_court.scenario.checks import check_case, earliest_step
from llm_court.scenario.drafts import (
    DraftError,
    HiddenTruthOutput,
    LearningPointsOutput,
    Materials,
    MaterialsOutput,
    TrapsOutput,
    attach_traps,
    to_hidden_truth,
    to_learning_points,
    to_materials,
)
from llm_court.scenario.solver import CaseSolver, summarize_runs

logger = logging.getLogger(__name__)

ProgressFn = Callable[[str], None]
ResearchFn = Callable[[str, ProgressFn], Awaitable[ResearchReport]]


class CaseGenerationError(Exception):
    """上限まで作り直しても事件を作れなかった。"""


@dataclass
class _Tracker:
    """生成中の記録(プロンプトのバージョンと作り直しの回数)。"""

    prompt_versions: dict[str, str] = field(default_factory=dict[str, str])
    regenerations: Counter[str] = field(default_factory=Counter[str])


class CaseGenerator:
    def __init__(
        self,
        *,
        llm: LLMClient,
        recorder: InMemoryRecorder,
        prompts: PromptLoader,
        mode: TrialMode,
        settings: ScenarioSettings,
        research: ResearchFn | None = None,
    ) -> None:
        self._llm = llm
        self._recorder = recorder
        self._prompts = prompts
        self._mode = mode
        self._settings = settings
        self._research = research
        self._solver = CaseSolver(llm, prompts)

    # --- 各段階 ---

    async def _draft[T: BaseModel, R](
        self,
        name: str,
        schema: type[T],
        render: Callable[[list[str]], RenderedPrompt],
        convert: Callable[[T], R],
        tracker: _Tracker,
        feedback: Sequence[str] = (),
    ) -> R:
        """1 段階を生成して変換する。参照が不正なら問題点を伝えて作り直す。"""
        problems = list(feedback)
        for attempt in range(self._settings.draft_retries + 1):
            prompt = render(problems)
            tracker.prompt_versions[prompt.name] = prompt.version
            result = await self._llm.generate_structured(Role.SCENARIO_WRITER, prompt, schema)
            try:
                return convert(result.value)
            except DraftError as e:
                logger.info("%s の参照が不正なため作り直します(%d 回目): %s", name, attempt + 1, e)
                tracker.regenerations[name] += 1
                problems = e.problems
        raise CaseGenerationError(f"{name} を作れませんでした: {'; '.join(problems)}")

    async def learning_points(
        self, theme: str, evidence: Sequence[Evidence], tracker: _Tracker
    ) -> list[LearningPoint]:
        lo, hi = self._mode.learning_points
        return await self._draft(
            "learning_points",
            LearningPointsOutput,
            lambda fb: self._prompts.render(
                "scenario_writer/learning_points",
                theme=theme,
                evidence=[e for e in evidence if e.verified_facts],
                count_min=lo,
                count_max=hi,
                feedback=fb,
            ),
            lambda out: to_learning_points(out, evidence, hi),
            tracker,
        )

    async def hidden_truth(
        self,
        theme: str,
        learning_points: Sequence[LearningPoint],
        tracker: _Tracker,
        feedback: Sequence[str] = (),
    ) -> tuple[list[Person], HiddenTruth]:
        m = self._mode
        return await self._draft(
            "hidden_truth",
            HiddenTruthOutput,
            lambda fb: self._prompts.render(
                "scenario_writer/hidden_truth",
                theme=theme,
                learning_points=learning_points,
                people_min=m.people[0],
                people_max=m.people[1],
                events_min=m.timeline_events[0],
                events_max=m.timeline_events[1],
                lies_min=m.lies[0],
                lies_max=m.lies[1],
                feedback=fb,
            ),
            lambda out: to_hidden_truth(out, learning_points),
            tracker,
            feedback,
        )

    async def materials(
        self,
        theme: str,
        learning_points: Sequence[LearningPoint],
        people: Sequence[Person],
        truth: HiddenTruth,
        tracker: _Tracker,
        feedback: Sequence[str] = (),
    ) -> Materials:
        m = self._mode
        return await self._draft(
            "materials",
            MaterialsOutput,
            lambda fb: self._prompts.render(
                "scenario_writer/materials",
                theme=theme,
                learning_points=learning_points,
                people=people,
                truth=truth,
                evidence_min=m.evidence[0],
                evidence_max=m.evidence[1],
                options_min=m.question_options[0],
                options_max=m.question_options[1],
                feedback=fb,
            ),
            lambda out: to_materials(out, people, truth, learning_points),
            tracker,
            feedback,
        )

    async def traps(
        self,
        learning_points: Sequence[LearningPoint],
        materials: Materials,
        tracker: _Tracker,
        feedback: Sequence[str] = (),
    ) -> list[Contradiction]:
        lines = {line.id: line for t in materials.testimonies for line in t.lines}
        per = self._mode.traps_per_contradiction
        return await self._draft(
            "traps",
            TrapsOutput,
            lambda fb: self._prompts.render(
                "scenario_writer/traps",
                learning_points=learning_points,
                evidence=materials.evidence,
                contradictions=materials.contradictions,
                lines=lines,
                per_contradiction=per,
                feedback=fb,
            ),
            lambda out: attach_traps(
                out, materials.contradictions, materials.evidence, learning_points, per
            ),
            tracker,
            feedback,
        )

    # --- 全体 ---

    async def generate(
        self,
        theme: str,
        *,
        evidence: ResearchReport | None = None,
        on_progress: ProgressFn | None = None,
    ) -> Case:
        """事件を生成して検証する。解けない場合は上限まで作り直し、それでも解けなければ
        最後の事件を `validation.solved=False` のまま返す(保存して調べられるように)。"""

        def progress(message: str) -> None:
            logger.debug(message)
            if on_progress:
                on_progress(message)

        tracker = _Tracker()
        started = len(self._recorder.records)
        if evidence is None:
            if self._research is None:
                raise CaseGenerationError("捜査結果も捜査手段も指定されていません")
            progress("捜査しています")
            evidence = await self._research(theme, progress)
        if not any(e.verified_facts for e in evidence.evidence):
            raise CaseGenerationError("検証済みの事実を持つ証拠品がありません")

        progress("学習ポイントを選んでいます")
        lps = await self.learning_points(theme, evidence.evidence, tracker)
        progress("真相を作っています")
        people, truth = await self.hidden_truth(theme, lps, tracker)
        progress("証拠品・証言・台本を作っています")
        materials = await self.materials(theme, lps, people, truth, tracker)
        progress("罠を作っています")
        contradictions = await self.traps(lps, materials, tracker)

        case_id = uuid.uuid4().hex[:10]
        case: Case | None = None
        for round_ in range(self._settings.max_regenerations + 1):
            case = self._assemble(
                case_id, theme, evidence, lps, people, truth, materials, contradictions
            )
            issues = check_case(case, self._mode)
            step = earliest_step(issues)
            if step is None:
                progress(f"solver で検証しています({self._settings.solver_runs} 回)")
                validation = await self._solver.validate(
                    case, self._settings.solver_runs, issues, self._settings.min_solve_rate
                )
                case = case.model_copy(update={"validation": validation})
                if validation.solved:
                    progress(f"solver が解けました(解答率 {validation.solve_rate:.0%})")
                    break
                feedback = _solver_feedback(case)
                step = "materials"
            else:
                # 整合性チェックに失敗した事件は solver にかけない(検証結果にはチェック結果だけ残す)
                feedback = [i.message for i in issues if i.step == step]
                case = case.model_copy(update={"validation": summarize_runs([], issues)})
            if round_ == self._settings.max_regenerations:
                break
            tracker.regenerations[f"round:{step}"] += 1
            progress(f"作り直しています({step}、{round_ + 1} 回目)")
            if step == "learning_points":
                lps = await self.learning_points(theme, evidence.evidence, tracker)
                step = "hidden_truth"
            if step == "hidden_truth":
                people, truth = await self.hidden_truth(theme, lps, tracker, feedback)
                step = "materials"
                feedback = []
            if step == "materials":
                materials = await self.materials(theme, lps, people, truth, tracker, feedback)
                feedback = []
            contradictions = await self.traps(lps, materials, tracker, feedback)

        assert case is not None
        return case.model_copy(update={"generation": self._generation(tracker, started)})

    async def validate(self, case: Case, runs: int | None = None) -> Case:
        """保存済みの事件を検証し直す(整合性チェックと solver)。"""
        issues = check_case(case, self._mode)
        validation = await self._solver.validate(
            case, runs or self._settings.solver_runs, issues, self._settings.min_solve_rate
        )
        return case.model_copy(update={"validation": validation})

    def _assemble(
        self,
        case_id: str,
        theme: str,
        research: ResearchReport,
        lps: list[LearningPoint],
        people: list[Person],
        truth: HiddenTruth,
        materials: Materials,
        contradictions: list[Contradiction],
    ) -> Case:
        return Case(
            id=case_id,
            theme=theme,
            title=materials.title,
            created_at=datetime.now(UTC),
            overview=materials.overview,
            question=materials.question,
            people=people,
            evidence=materials.evidence,
            testimonies=materials.testimonies,
            learning_points=lps,
            hidden_truth=truth,
            witness_scripts=materials.witness_scripts,
            contradictions=contradictions,
            research=research,
        )

    def _generation(self, tracker: _Tracker, started: int) -> CaseGeneration:
        records = self._recorder.records[started:]
        extra: dict[str, Any] = {
            "structured_failures": sum(not r.success for r in records if r.kind == "structured")
        }
        return CaseGeneration(
            models={
                role.value: self._llm.config.resolve(role).model.model
                for role in (Role.RESEARCHER, Role.SCENARIO_WRITER, Role.SOLVER)
            },
            prompt_versions=tracker.prompt_versions,
            regenerations=dict(tracker.regenerations),
            llm_calls=len(records),
            input_tokens=sum(r.input_tokens or 0 for r in records),
            output_tokens=sum(r.output_tokens or 0 for r in records),
            llm_time_s=sum(r.total_ms for r in records) / 1000,
            extra=extra,
        )


def _solver_feedback(case: Case) -> list[str]:
    """solver が解けなかった理由を、solver の実際のつきつけとともに資料の作り直しの問題点にする。"""
    validation = case.validation
    runs = validation.solver_runs if validation else []
    if not runs:
        return ["solver が解答を出せませんでした。資料を簡潔で一貫したものにしてください"]
    lines = case.testimony_lines
    by_line = {c.testimony_line_id: c for c in case.contradictions}
    found = {cid for r in runs for cid in r.found}
    problems: list[str] = []
    reported: set[tuple[str, str]] = set()
    for run in runs:
        for a in run.accusations:
            key = (a.testimony_line_id, a.evidence_id)
            c = by_line.get(a.testimony_line_id)
            if key in reported or (c is not None and c.evidence_id == a.evidence_id):
                continue
            reported.add(key)
            text = lines[a.testimony_line_id].text if a.testimony_line_id in lines else "?"
            if c is not None:
                problems.append(
                    f"証言「{text}」の嘘に、正解の {c.evidence_id} ではなく {a.evidence_id} で"
                    "気づかれました。決め手が一つに決まるよう、ほかの証拠品で同じ矛盾を示せないようにし、"
                    f"{c.evidence_id} の記載を具体的にしてください"
                )
            else:
                problems.append(
                    f"嘘でない証言「{text}」が {a.evidence_id} と矛盾して見えました。"
                    "真実の証言が証拠品と食い違わないようにしてください"
                )
    for c in case.contradictions:
        if c.id not in found and not any(c.id in r.near_misses for r in runs):
            problems.append(
                f"証言「{lines[c.testimony_line_id].text}」の嘘に気づかれませんでした。"
                f"{c.evidence_id} の記載に、学習ポイントの知識を当てはめると食い違うとわかる"
                "具体的な数値・日時・条件を書いてください"
            )
    wrong_answers = [r for r in runs if not r.answer_correct]
    if wrong_answers:
        detected = any(r.steps is not None for r in wrong_answers)
        problems.append(
            f"最後の問いに {len(runs)} 回中 {len(wrong_answers)} 回誤答しました"
            + ("(矛盾をすべて見つけた回でも誤答)" if detected else "")
            + "。問いは評価や程度(「最も重大な」など)を問わず、矛盾を解けば一つに決まる事実"
            "(誰が・いつ・何を)を問う形にし、正解以外の選択肢は矛盾から明確に否定できるものにしてください"
        )
    return problems
