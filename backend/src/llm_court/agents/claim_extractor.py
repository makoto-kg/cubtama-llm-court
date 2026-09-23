"""発言から主張を構造化して取り出す書記官。"""

from pydantic import BaseModel, Field

from llm_court.config import Role
from llm_court.domain import ClaimKind, Statement
from llm_court.llm import LLMClient, PromptLoader, StructuredResult


class ClaimDraft(BaseModel):
    text: str = Field(min_length=1, description="主張の要約(1文)")
    kind: ClaimKind = Field(description="fact / value / inference")
    cited_evidence_ids: list[str] = Field(description="出典の証拠品 ID")


class ClaimList(BaseModel):
    claims: list[ClaimDraft] = Field(max_length=8)


class ClaimExtractorAgent:
    def __init__(self, llm: LLMClient, prompts: PromptLoader) -> None:
        self._llm = llm
        self._prompts = prompts

    async def extract(self, topic: str, statement: Statement) -> StructuredResult[ClaimList]:
        prompt = self._prompts.render(
            "claim_extractor/extract",
            topic=topic,
            side_label=statement.side.label,
            phase_label=statement.phase.label,
            text=statement.text,
        )
        return await self._llm.generate_structured(Role.CLAIM_EXTRACTOR, prompt, ClaimList)
