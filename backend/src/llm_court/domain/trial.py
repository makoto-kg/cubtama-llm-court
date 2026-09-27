"""裁判型のプレイ(尋問の選択肢・証人の応答・逸脱の判定・解説)のモデル。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from llm_court.domain.case import LearningPoint
from llm_court.domain.choices import Strength


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


TrialAction = Literal["present", "probe"]
"""present: 証拠品をつきつける / probe: ゆさぶる(証言の行に説明を求める)。"""


class TrialOption(_Frozen):
    """尋問の選択肢。`strength` などは選ぶまでプレイヤーに見せない。"""

    id: str
    kind: TrialAction
    line_id: str
    evidence_id: str | None = None
    label: str
    strength: Strength | None = None
    """present の強さ(正解 = strong、罠 = trap、それ以外 = weak)。probe は None。"""
    contradiction_id: str | None = None
    """正解の組なら、その矛盾の ID(非公開)。"""
    trap_reason: str | None = None
    """罠なら、なぜ選びたくなるか(非公開。解説で使う)。"""

    def redacted(self) -> "TrialOption":
        return self.model_copy(
            update={"strength": None, "contradiction_id": None, "trap_reason": None}
        )


DeviationKind = Literal["premature_confession", "failed_collapse", "leak"]


class DeviationCheck(_Frozen):
    """証人の応答が台本から逸脱していないかの判定。"""

    confessed: bool
    """嘘を認めた(崩れた)か。"""
    leaked_fact_indices: list[int]
    """漏らした隠している事実の番号(台本の hidden_facts の 0 始まり)。"""
    deviations: list[DeviationKind]
    reason: str


TrialResult = Literal["solved", "wrong_answer", "penalty"]


class ExplanationTrap(_Frozen):
    evidence_id: str
    evidence_name: str
    reasoning: str
    why_tempting: str
    learning_point_id: str
    misconception: str


class ExplanationItem(_Frozen):
    """1 つの矛盾の解説。"""

    contradiction_id: str
    witness_name: str
    testimony_line_id: str
    testimony_line: str
    evidence_id: str
    evidence_name: str
    explanation: str
    learning_point_ids: list[str]
    traps: list[ExplanationTrap]


class Explanation(_Frozen):
    """閉廷後の解説(事件のデータだけから組み立てる。LLM で書かない)。"""

    title: str
    truth: str
    question: str
    answer: str
    items: list[ExplanationItem]
    learning_points: list[LearningPoint]
