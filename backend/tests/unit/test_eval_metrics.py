import pytest

from llm_court.domain import JudgeScore, Side
from llm_court.eval.metrics import (
    margin_stdev,
    order_flip_rate,
    percentile,
    ratio,
    reference_agreement,
    repeat_stability,
    verdict_label,
)
from llm_court.eval.models import DebateRun, Judging, JudgingSource
from llm_court.modes import DEBATE_MODE

AN = [Side.AFFIRMATIVE, Side.NEGATIVE]
NA = [Side.NEGATIVE, Side.AFFIRMATIVE]


def score(aff: int, neg: int, order: list[Side]) -> JudgeScore:
    keys = [c.key for c in DEBATE_MODE.rubric]
    return JudgeScore(
        order=order,
        scores={
            Side.AFFIRMATIVE: dict.fromkeys(keys, aff),
            Side.NEGATIVE: dict.fromkeys(keys, neg),
        },
        rationale="理由",
    )


def judging(a: tuple[int, int], b: tuple[int, int], source: JudgingSource = "repeat") -> Judging:
    scores = [score(*a, AN), score(*b, NA)]
    return Judging(source=source, scores=scores, verdict=DEBATE_MODE.decide(scores))


def test_percentile() -> None:
    assert percentile([], 0.5) is None
    assert percentile([3.0], 0.9) == 3.0
    assert percentile([1.0, 2.0, 3.0, 4.0], 0.5) == 2.5
    assert percentile([4.0, 1.0, 3.0, 2.0], 0.9) == pytest.approx(3.7)


def test_ratio() -> None:
    assert ratio(1, 4) == 0.25
    assert ratio(1, 0) is None


def test_order_flip_rate() -> None:
    agreed = judging((8, 6), (7, 5))
    flipped = judging((8, 6), (5, 7))
    assert order_flip_rate([agreed, flipped, agreed, agreed]) == 0.25
    assert order_flip_rate([]) is None


def test_repeat_stability() -> None:
    aff = judging((8, 6), (7, 5))
    draw = judging((8, 6), (5, 7))
    assert verdict_label(aff.verdict) == "affirmative"
    assert verdict_label(draw.verdict) == "draw"
    assert repeat_stability([aff, aff, draw]) == pytest.approx(2 / 3)
    assert repeat_stability([aff]) is None


def test_margin_stdev() -> None:
    # 点差(×4 項目): +8, +8, +8, +8 → 0
    assert margin_stdev([judging((8, 6), (8, 6)), judging((8, 6), (8, 6))]) == 0
    # +8 と −8 → 8
    assert margin_stdev([judging((8, 6), (6, 8))]) == 8
    assert margin_stdev([]) is None


def _run(own: Judging, ref: Judging | None) -> DebateRun:
    judgings = [own.model_copy(update={"source": "debate"})]
    if ref is not None:
        judgings.append(ref.model_copy(update={"source": "reference"}))
    return DebateRun(
        config="a", topic="t", run=1, session_id="s", events=[], judgings=judgings, judge_calls=[]
    )


def test_reference_agreement() -> None:
    aff = judging((8, 6), (7, 5))
    neg = judging((5, 7), (5, 7))
    runs = [_run(aff, aff), _run(aff, neg), _run(neg, None)]
    assert reference_agreement(runs) == 0.5
    assert reference_agreement([_run(aff, None)]) is None
