"""ディベート型のモード定義。"""

from pydantic import BaseModel, ConfigDict

from llm_court.domain import DebatePhase, JudgeScore, Side, Verdict


class RubricCriterion(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str
    name: str
    description: str


class Turn(BaseModel):
    """進行表の 1 手番。"""

    model_config = ConfigDict(frozen=True)

    phase: DebatePhase
    round: int
    side: Side


class DebateMode(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str = "debate"
    score_min: int = 1
    score_max: int = 10
    rubric: tuple[RubricCriterion, ...] = (
        RubricCriterion(
            key="logic",
            name="論理の一貫性",
            description="主張と根拠がつながっており、自己矛盾や論理の飛躍がないか",
        ),
        RubricCriterion(
            key="evidence",
            name="証拠の使い方",
            description="証拠品を正確に引用し、主張の裏付けとして適切に使っているか",
        ),
        RubricCriterion(
            key="rebuttal",
            name="反論の的確さ",
            description="相手の主張の弱点を具体的に突き、相手の反論に応えているか",
        ),
        RubricCriterion(
            key="persuasiveness",
            name="説得力",
            description="第三者が聞いて納得できる明快さと構成になっているか",
        ),
    )
    contradiction_types: dict[str, str] = {
        "self_contradiction": "自己矛盾(同じ陣営の主張どうしが食い違う)",
        "evidence_conflict": "証拠との矛盾(主張が証拠品の内容と食い違う)",
        "logical_leap": "論理の飛躍(根拠から結論が導けない)",
        "definition_shift": "定義のすり替え(途中で言葉の意味を変える)",
        "fabricated_citation": "引用の捏造(証拠品にない内容を証拠として示す)",
    }
    """矛盾候補の種類(分析官で使う)。"""
    phase_guides: dict[DebatePhase, str] = {
        DebatePhase.OPENING: (
            "冒頭陳述です。自分の立場と主要な論点を示し、証拠品を使って根拠を述べてください。"
        ),
        DebatePhase.REBUTTAL: (
            "反論です。相手の直前の発言と主張ログを踏まえ、相手の主張の弱点を具体的に指摘し、"
            "自分の論点を補強してください。"
        ),
        DebatePhase.CLOSING: (
            "最終弁論です。これまでの議論を総括し、自分の側が優れている理由を簡潔にまとめてください。"
            "新しい論点は出さないでください。"
        ),
    }
    target_chars: dict[DebatePhase, int] = {
        DebatePhase.OPENING: 500,
        DebatePhase.REBUTTAL: 400,
        DebatePhase.CLOSING: 350,
    }

    def schedule(self, rounds: int) -> list[Turn]:
        """冒頭陳述 → 反論 × rounds → 最終弁論。各フェーズとも肯定側が先。"""
        turns = [Turn(phase=DebatePhase.OPENING, round=0, side=s) for s in Side]
        for r in range(1, rounds + 1):
            turns += [Turn(phase=DebatePhase.REBUTTAL, round=r, side=s) for s in Side]
        turns += [Turn(phase=DebatePhase.CLOSING, round=0, side=s) for s in Side]
        return turns

    def decide(self, scores: list[JudgeScore]) -> Verdict:
        """評価ごとの勝者(合計点)がすべて一致すればその陣営、そうでなければ引き分け。"""
        if not scores:
            raise ValueError("評価がありません")
        winners = {s.winner for s in scores}
        agreed = len(winners) == 1
        winner = next(iter(winners)) if agreed else None
        totals = {side: sum(s.total(side) for s in scores) / len(scores) for side in Side}
        rationale = "\n\n".join(
            f"評価 {i}(提示順: {' → '.join(side.label for side in s.order)}): {s.rationale}"
            for i, s in enumerate(scores, start=1)
        )
        return Verdict(winner=winner, agreed=agreed, totals=totals, rationale=rationale)


DEBATE_MODE = DebateMode()
