import pytest

from llm_court.agents.judge import JudgeOutput, RubricScores
from llm_court.domain import DebatePhase, JudgeScore, Side
from llm_court.modes import DEBATE_MODE


def test_rubric_matches_judge_schema() -> None:
    assert [c.key for c in DEBATE_MODE.rubric] == list(RubricScores.model_fields)


def test_schedule() -> None:
    turns = DEBATE_MODE.schedule(2)
    assert [(t.phase, t.round, t.side) for t in turns] == [
        (DebatePhase.OPENING, 0, Side.AFFIRMATIVE),
        (DebatePhase.OPENING, 0, Side.NEGATIVE),
        (DebatePhase.REBUTTAL, 1, Side.AFFIRMATIVE),
        (DebatePhase.REBUTTAL, 1, Side.NEGATIVE),
        (DebatePhase.REBUTTAL, 2, Side.AFFIRMATIVE),
        (DebatePhase.REBUTTAL, 2, Side.NEGATIVE),
        (DebatePhase.CLOSING, 0, Side.AFFIRMATIVE),
        (DebatePhase.CLOSING, 0, Side.NEGATIVE),
    ]
    assert all(t.phase in DEBATE_MODE.phase_guides for t in turns)


def _score(aff: int, neg: int, order: list[Side]) -> JudgeScore:
    keys = [c.key for c in DEBATE_MODE.rubric]
    return JudgeScore(
        order=order,
        scores={
            Side.AFFIRMATIVE: dict.fromkeys(keys, aff),
            Side.NEGATIVE: dict.fromkeys(keys, neg),
        },
        rationale="理由",
    )


AN = [Side.AFFIRMATIVE, Side.NEGATIVE]
NA = [Side.NEGATIVE, Side.AFFIRMATIVE]


def test_decide_agreed() -> None:
    verdict = DEBATE_MODE.decide([_score(8, 6, AN), _score(7, 5, NA)])
    assert verdict.winner is Side.AFFIRMATIVE
    assert verdict.agreed
    assert verdict.totals[Side.AFFIRMATIVE] == 30.0
    assert verdict.totals[Side.NEGATIVE] == 22.0
    assert "否定側 → 肯定側" in verdict.rationale


def test_decide_disagreement_is_draw() -> None:
    verdict = DEBATE_MODE.decide([_score(8, 6, AN), _score(5, 7, NA)])
    assert verdict.winner is None
    assert not verdict.agreed


def test_decide_tie_is_draw() -> None:
    verdict = DEBATE_MODE.decide([_score(7, 7, AN), _score(7, 7, NA)])
    assert verdict.winner is None
    assert verdict.agreed


def test_decide_requires_scores() -> None:
    with pytest.raises(ValueError):
        DEBATE_MODE.decide([])


VALID_RATIONALE = (
    "肯定側は証拠品を正確に引用し、否定側は財源の課題を示した。両者とも論理は明快だった。" * 2
)


def test_judge_output_accepts_plain_japanese() -> None:
    scores = RubricScores(logic=5, evidence=5, rebuttal=5, persuasiveness=5)
    out = JudgeOutput(affirmative=scores, negative=scores, rationale=VALID_RATIONALE)
    assert out.rationale == VALID_RATIONALE


@pytest.mark.parametrize(
    "rationale",
    [
        VALID_RATIONALE + "<|end|><|start|>assistant",
        "## 評価\n" + VALID_RATIONALE,
        "| 項目 | 点 |\n" + VALID_RATIONALE,
        "Both sides present coherent arguments but differ in how tightly they link claims. " * 2,
    ],
)
def test_judge_output_rejects_noise(rationale: str) -> None:
    scores = RubricScores(logic=5, evidence=5, rebuttal=5, persuasiveness=5)
    with pytest.raises(ValueError):
        JudgeOutput(affirmative=scores, negative=scores, rationale=rationale)
