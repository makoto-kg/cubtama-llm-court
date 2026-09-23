"""裁判長。発言ブロックの提示順を変えて評価できる。"""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from pydantic import BaseModel, Field, field_validator

from llm_court.config import Role
from llm_court.domain import CitationIssue, Evidence, JudgeScore, Side, Statement
from llm_court.llm import LLMClient, PromptLoader, StructuredResult
from llm_court.modes import DebateMode


class RubricScores(BaseModel):
    logic: int = Field(ge=1, le=10, description="論理の一貫性")
    evidence: int = Field(ge=1, le=10, description="証拠の使い方")
    rebuttal: int = Field(ge=1, le=10, description="反論の的確さ")
    persuasiveness: int = Field(ge=1, le=10, description="説得力")


_JAPANESE = re.compile(r"[\u3040-\u30ff]")
_MARKDOWN = re.compile(r"(^|\n)\s*(#{1,6}\s|\|.*\||[-*]\s)")


class JudgeOutput(BaseModel):
    affirmative: RubricScores
    negative: RubricScores
    rationale: str = Field(
        min_length=50, max_length=1000, description="採点の理由(日本語の地の文、200〜400字)"
    )

    @field_validator("rationale")
    @classmethod
    def _plain_japanese(cls, value: str) -> str:
        # モデルの内部トークンや Markdown・英語の混入は再試行させる
        if "<|" in value:
            raise ValueError(
                "rationale に制御トークンが含まれています。理由の文章だけを書いてください"
            )
        if _MARKDOWN.search(value):
            raise ValueError("rationale に見出し・表・箇条書きを使わず、地の文で書いてください")
        if len(_JAPANESE.findall(value)) < len(value) * 0.2:
            raise ValueError("rationale は日本語で書いてください")
        return value.strip()


@dataclass(frozen=True)
class _Block:
    label: str
    statements: list[Statement]
    issues: list[CitationIssue]


@dataclass(frozen=True)
class JudgeResult:
    score: JudgeScore
    result: StructuredResult[JudgeOutput]


class JudgeAgent:
    def __init__(self, llm: LLMClient, prompts: PromptLoader, mode: DebateMode) -> None:
        self._llm = llm
        self._prompts = prompts
        self._mode = mode

    async def evaluate(
        self,
        *,
        topic: str,
        order: Sequence[Side],
        evidence: Sequence[Evidence],
        statements: Sequence[Statement],
        issues: Sequence[CitationIssue],
    ) -> JudgeResult:
        """陣営ごとの発言ブロックを `order` の順に並べて採点させる。"""
        side_of = {s.id: s.side for s in statements}
        blocks = [
            _Block(
                label=side.label,
                statements=[s for s in statements if s.side is side],
                issues=[i for i in issues if side_of.get(i.statement_id) is side],
            )
            for side in order
        ]
        prompt = self._prompts.render(
            "judge/verdict",
            topic=topic,
            rubric=self._mode.rubric,
            score_min=self._mode.score_min,
            score_max=self._mode.score_max,
            evidence=evidence,
            blocks=blocks,
        )
        result = await self._llm.generate_structured(Role.JUDGE, prompt, JudgeOutput)
        output = result.value
        score = JudgeScore(
            order=list(order),
            scores={
                Side.AFFIRMATIVE: output.affirmative.model_dump(),
                Side.NEGATIVE: output.negative.model_dump(),
            },
            rationale=output.rationale,
        )
        return JudgeResult(score=score, result=result)
