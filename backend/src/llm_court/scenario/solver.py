"""solver による事件の検証。公開情報だけを渡して解かせ、解けるか・一意か・何手かを調べる。"""

import asyncio
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from llm_court.config import Role
from llm_court.domain import Case, CaseValidation, CheckIssue, SolverAccusation, SolverRun
from llm_court.llm import LLMClient, LLMConnectionError, LLMError, PromptLoader


class AccusationDraft(BaseModel):
    testimony_line_id: str
    evidence_id: str
    reasoning: str = Field(min_length=1)


class SolverOutput(BaseModel):
    accusations: list[AccusationDraft] = Field(min_length=1, max_length=10)
    answer_index: int = Field(ge=0)


def score(case: Case, output: SolverOutput) -> SolverRun:
    """つきつけを順に照合する。全矛盾を見つけ終えた手数と、正解にない指摘の数を数える。"""
    answers = {(c.testimony_line_id, c.evidence_id): c.id for c in case.contradictions}
    by_line = {c.testimony_line_id: c.id for c in case.contradictions}
    found: list[str] = []
    near_misses: list[str] = []
    extra = 0
    steps: int | None = None
    for n, accusation in enumerate(output.accusations, start=1):
        cid = answers.get((accusation.testimony_line_id, accusation.evidence_id))
        if cid is None:
            extra += 1
            near = by_line.get(accusation.testimony_line_id)
            if near is not None and near not in near_misses:
                near_misses.append(near)
        elif cid not in found:
            found.append(cid)
            if len(found) == len(answers):
                steps = n
    return SolverRun(
        accusations=[SolverAccusation(**a.model_dump()) for a in output.accusations],
        answer_index=output.answer_index,
        found=found,
        extra=extra,
        near_misses=[cid for cid in near_misses if cid not in found],
        steps=steps,
        answer_correct=output.answer_index == case.question.answer_index,
    )


def summarize_runs(runs: list[SolverRun], issues: list[CheckIssue]) -> CaseValidation:
    solved = any(r.solved for r in runs)
    unique = bool(runs) and all(
        r.answer_index == runs[0].answer_index
        and set(r.found) == set(runs[0].found)
        and r.extra == 0
        for r in runs
    )
    steps = [r.steps for r in runs if r.solved and r.steps is not None]
    return CaseValidation(
        validated_at=datetime.now(UTC),
        issues=issues,
        solver_runs=runs,
        solved=solved,
        solve_rate=sum(r.solved for r in runs) / len(runs) if runs else 0.0,
        unique=unique,
        min_steps=min(steps) if steps else None,
    )


class CaseSolver:
    def __init__(self, llm: LLMClient, prompts: PromptLoader) -> None:
        self._llm = llm
        self._prompts = prompts

    async def solve_once(self, case: Case) -> SolverRun | None:
        prompt = self._prompts.render("solver/solve", case=case.public_view())
        try:
            result = await self._llm.generate_structured(Role.SOLVER, prompt, SolverOutput)
        except LLMConnectionError:
            raise
        except LLMError:
            return None  # 失敗は計測記録に残る
        return score(case, result.value)

    async def validate(self, case: Case, runs: int, issues: list[CheckIssue]) -> CaseValidation:
        results = await asyncio.gather(*(self.solve_once(case) for _ in range(runs)))
        return summarize_runs([r for r in results if r is not None], issues)
