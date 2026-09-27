"""証人。台本(人物像・隠している事実・嘘・崩れる条件)の範囲で、尋問に即興で答える。"""

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass

from llm_court.config import Role
from llm_court.domain import Case, CollapseCondition, Testimony, TrialOption, WitnessScript
from llm_court.llm import LLMClient, PromptLoader, RenderedPrompt


@dataclass(frozen=True)
class Exchange:
    """これまでのやりとり(尋問の見出しと証人の応答)。"""

    action: str
    text: str


def collapse_for(case: Case, option: TrialOption) -> CollapseCondition | None:
    """正解の組なら、台本の崩れる条件を返す。"""
    if option.contradiction_id is None:
        return None
    contradiction = next(c for c in case.contradictions if c.id == option.contradiction_id)
    for script in case.witness_scripts:
        for cond in script.collapse_conditions:
            if cond.lie_id == contradiction.lie_id:
                return cond
    return CollapseCondition(
        lie_id=contradiction.lie_id,
        evidence_id=contradiction.evidence_id,
        reaction="動揺して証言の誤りを認める",
    )


def script_for(case: Case, witness_id: str) -> WitnessScript:
    script = next((s for s in case.witness_scripts if s.witness_id == witness_id), None)
    if script is not None:
        return script
    return WitnessScript(
        witness_id=witness_id,
        persona="落ち着いた話し方",
        hidden_facts=[],
        lie_ids=[lie.id for lie in case.hidden_truth.lies if lie.witness_id == witness_id],
        collapse_conditions=[],
    )


class WitnessAgent:
    def __init__(self, llm: LLMClient, prompts: PromptLoader, *, history_limit: int = 4) -> None:
        self._llm = llm
        self._prompts = prompts
        self._history_limit = history_limit

    def build_prompt(
        self,
        *,
        case: Case,
        testimony: Testimony,
        option: TrialOption,
        history: Sequence[Exchange],
    ) -> RenderedPrompt:
        people = {p.id: p for p in case.people}
        script = script_for(case, testimony.witness_id)
        lie_ids = set(script.lie_ids) | {
            lie.id for lie in case.hidden_truth.lies if lie.witness_id == testimony.witness_id
        }
        line = next(line for line in testimony.lines if line.id == option.line_id)
        evidence = next((e for e in case.evidence if e.id == option.evidence_id), None)
        return self._prompts.render(
            "witness/respond",
            witness=people[testimony.witness_id],
            script=script,
            lies=[lie for lie in case.hidden_truth.lies if lie.id in lie_ids],
            case_title=case.title,
            overview=case.overview,
            testimony=testimony,
            history=list(history)[-self._history_limit :],
            option=option,
            line=line,
            evidence=evidence,
            collapse=collapse_for(case, option),
        )

    def stream(self, prompt: RenderedPrompt) -> AsyncIterator[str]:
        return self._llm.stream_text(Role.WITNESS, prompt)
