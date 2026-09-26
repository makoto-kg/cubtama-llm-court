"""人間 vs LLM で人間に示す選択肢(分析官の候補)。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ContradictionType = Literal[
    "self_contradiction",
    "evidence_conflict",
    "logical_leap",
    "definition_shift",
    "fabricated_citation",
]
Strength = Literal["strong", "weak", "trap"]
"""strong: 有効な指摘 / weak: 弱い指摘 / trap: 実は矛盾ではない(罠)。"""

ChoiceKind = Literal["contradiction", "probe", "argument"]
"""contradiction: 矛盾をつきつける / probe: ゆさぶる(質問) / argument: 論点の方針(冒頭・最終)。"""


class ContradictionCandidate(BaseModel):
    """矛盾候補。`evidence_id` と `other_claim_id` はどちらか(または両方なし)。"""

    model_config = ConfigDict(frozen=True)

    target_claim_id: str
    evidence_id: str | None = None
    other_claim_id: str | None = None
    type: ContradictionType
    strength: Strength | None
    """None は API で伏せた状態(未選択の選択肢)。ストアには常に値がある。"""
    rationale: str | None
    """強さの判断理由(プレイヤーには選択後まで見せない)。"""


class ChoiceOption(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    kind: ChoiceKind
    label: str
    """表示用の見出し(どの主張に/何をつきつけて/どの論法で)。"""
    pitch: str
    """プレイヤーに見せる指摘・方針の要旨。代弁者はこれをもとに発言を清書する。"""
    contradiction: ContradictionCandidate | None = None
    target_claim_id: str | None = None
    """probe の対象の主張。"""
    evidence_ids: list[str] = Field(default_factory=list)
    """argument で使う証拠品。"""
    source: Literal["analyst", "rule"] | None = "analyst"
    """rule: 引用の機械検査から自動で作った候補。None は API で伏せた状態。"""

    @property
    def strength(self) -> Strength | None:
        return self.contradiction.strength if self.contradiction else None

    def redacted(self) -> "ChoiceOption":
        """強さ・判断理由・由来を伏せた形(未選択の選択肢をプレイヤーに見せるとき)。"""
        contradiction = (
            self.contradiction.model_copy(update={"strength": None, "rationale": None})
            if self.contradiction
            else None
        )
        return self.model_copy(update={"contradiction": contradiction, "source": None})
