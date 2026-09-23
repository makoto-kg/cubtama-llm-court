"""ディベートのドメインモデル(陣営、フェーズ、発言、主張、引用の問題、採点、判決)。"""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Side(StrEnum):
    AFFIRMATIVE = "affirmative"
    NEGATIVE = "negative"

    @property
    def label(self) -> str:
        return "肯定側" if self is Side.AFFIRMATIVE else "否定側"

    @property
    def opponent(self) -> "Side":
        return Side.NEGATIVE if self is Side.AFFIRMATIVE else Side.AFFIRMATIVE


class DebatePhase(StrEnum):
    OPENING = "opening"
    REBUTTAL = "rebuttal"
    CLOSING = "closing"
    VERDICT = "verdict"

    @property
    def label(self) -> str:
        return {
            DebatePhase.OPENING: "冒頭陳述",
            DebatePhase.REBUTTAL: "反論",
            DebatePhase.CLOSING: "最終弁論",
            DebatePhase.VERDICT: "判決",
        }[self]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class Statement(_Frozen):
    """論者の発言。"""

    id: str
    side: Side
    phase: DebatePhase
    round: int = Field(ge=0)
    """反論フェーズの何往復目か(冒頭陳述・最終弁論は 0)。"""
    turn: int = Field(ge=1)
    """セッション内の通し番号。"""
    text: str = Field(min_length=1)
    cited_evidence_ids: list[str]


ClaimKind = Literal["fact", "value", "inference"]
"""事実主張 / 価値判断 / 推論。"""


class Claim(_Frozen):
    """発言から抽出した個々の主張。"""

    id: str
    statement_id: str
    side: Side
    text: str
    kind: ClaimKind
    cited_evidence_ids: list[str]


CitationIssueKind = Literal["unknown_evidence", "unsupported_quote", "no_citation"]


class CitationIssue(_Frozen):
    """発言中の出典の問題(存在しない証拠品、証拠品にない引用、出典なし)。"""

    statement_id: str
    kind: CitationIssueKind
    evidence_id: str | None = None
    detail: str


class JudgeScore(_Frozen):
    """裁判長の 1 回の評価。"""

    order: list[Side]
    """評価時に発言ブロックを提示した順。"""
    scores: dict[Side, dict[str, int]]
    """陣営ごとのルーブリック項目の点数。"""
    rationale: str

    def total(self, side: Side) -> int:
        return sum(self.scores[side].values())

    @property
    def winner(self) -> Side | None:
        """合計点の高い陣営。同点なら None。"""
        aff, neg = self.total(Side.AFFIRMATIVE), self.total(Side.NEGATIVE)
        if aff == neg:
            return None
        return Side.AFFIRMATIVE if aff > neg else Side.NEGATIVE


class Verdict(_Frozen):
    winner: Side | None
    """勝者。引き分けなら None。"""
    agreed: bool
    """順序を入れ替えた評価で勝者が一致したか。"""
    totals: dict[Side, float]
    """評価ごとの合計点の平均。"""
    rationale: str
