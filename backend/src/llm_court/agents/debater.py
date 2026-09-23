"""論者(肯定側・否定側)。"""

from collections.abc import AsyncIterator, Sequence

from llm_court.config import Role
from llm_court.domain import Claim, DebatePhase, Evidence, Side, Statement
from llm_court.llm import LLMClient, PromptLoader, RenderedPrompt
from llm_court.modes import DebateMode


class DebaterAgent:
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
        evidence: Sequence[Evidence],
        claims: Sequence[Claim],
        statements: Sequence[Statement],
    ) -> RenderedPrompt:
        """文脈は証拠品の要約・主張ログ・相手の直前の発言全文に絞る。"""
        opponent_statement = next(
            (s for s in reversed(statements) if s.side is side.opponent), None
        )
        return self._prompts.render(
            "debater/statement",
            topic=topic,
            side_label=side.label,
            opponent_label=side.opponent.label,
            evidence=evidence,
            claims=claims,
            opponent_statement=opponent_statement,
            phase_guide=self._mode.phase_guides[phase],
            target_chars=self._mode.target_chars[phase],
        )

    def stream(self, prompt: RenderedPrompt) -> AsyncIterator[str]:
        return self._llm.stream_text(Role.DEBATER, prompt)
