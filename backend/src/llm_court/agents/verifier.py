"""矛盾候補の検証役(評価用)。候補の強さを分析官とは独立に判定する。"""

from collections.abc import Sequence

from pydantic import BaseModel, Field

from llm_court.config import Role
from llm_court.domain import Claim, ContradictionCandidate, Evidence, Statement, Strength
from llm_court.llm import LLMClient, PromptLoader, StructuredResult
from llm_court.modes import DebateMode


class CandidateVerdict(BaseModel):
    strength: Strength
    reason: str = Field(min_length=1, max_length=400)


class CandidateVerifier:
    def __init__(self, llm: LLMClient, prompts: PromptLoader, mode: DebateMode) -> None:
        self._llm = llm
        self._prompts = prompts
        self._mode = mode

    async def verify(
        self,
        *,
        topic: str,
        candidate: ContradictionCandidate,
        pitch: str,
        claims: Sequence[Claim],
        statements: Sequence[Statement],
        evidence: Sequence[Evidence],
    ) -> StructuredResult[CandidateVerdict]:
        claim_by_id = {c.id: c for c in claims}
        target = claim_by_id[candidate.target_claim_id]
        statement = next(s for s in statements if s.id == target.statement_id)
        prompt = self._prompts.render(
            "judge/verify_candidate",
            topic=topic,
            target_claim=target,
            target_statement=statement,
            evidence=next((e for e in evidence if e.id == candidate.evidence_id), None),
            other_claim=claim_by_id.get(candidate.other_claim_id or ""),
            type_label=self._mode.contradiction_types.get(candidate.type, candidate.type),
            pitch=pitch,
        )
        return await self._llm.generate_structured(Role.JUDGE, prompt, CandidateVerdict)
