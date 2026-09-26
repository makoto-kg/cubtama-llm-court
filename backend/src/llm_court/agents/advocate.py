"""代弁者。人間が選んだ選択肢を、人間側の発言として清書する。"""

from collections.abc import AsyncIterator, Sequence

from llm_court.config import Role
from llm_court.domain import ChoiceOption, Claim, DebatePhase, Evidence, Side, Statement
from llm_court.llm import LLMClient, PromptLoader, RenderedPrompt
from llm_court.modes import DebateMode


class AdvocateAgent:
    def __init__(self, llm: LLMClient, prompts: PromptLoader, mode: DebateMode) -> None:
        self._llm = llm
        self._prompts = prompts
        self._mode = mode

    def build_prompt(
        self,
        *,
        topic: str,
        side: Side,
        phase: DebatePhase,
        option: ChoiceOption,
        evidence: Sequence[Evidence],
        claims: Sequence[Claim],
        statements: Sequence[Statement],
    ) -> RenderedPrompt:
        claim_by_id = {c.id: c for c in claims}
        contradiction = option.contradiction
        target_id = contradiction.target_claim_id if contradiction else option.target_claim_id
        other_id = contradiction.other_claim_id if contradiction else None
        # argument では選んだ方針の証拠品を先頭に並べる
        used = [e for e in evidence if e.id in option.evidence_ids]
        ordered = used + [e for e in evidence if e not in used]
        return self._prompts.render(
            "advocate/statement",
            topic=topic,
            side_label=side.label,
            opponent_label=side.opponent.label,
            phase_label=phase.label,
            target_chars=self._mode.target_chars[phase],
            evidence=ordered,
            opponent_statement=next(
                (s for s in reversed(statements) if s.side is side.opponent), None
            ),
            option=option,
            target_claim=claim_by_id.get(target_id or ""),
            other_claim=claim_by_id.get(other_id or ""),
        )

    def stream(self, prompt: RenderedPrompt) -> AsyncIterator[str]:
        return self._llm.stream_text(Role.ADVOCATE, prompt)
