"""評価指標の計算(すべて純粋関数)。"""

import math
import statistics
from collections import Counter
from collections.abc import Iterable, Sequence

from pydantic import BaseModel, ConfigDict

from llm_court.domain import LLMCallInfo, Side, Verdict
from llm_court.engine.citations import check_citations, count_checked_quotes, extract_citations
from llm_court.engine.state import DebateState
from llm_court.engine.summary import summarize
from llm_court.eval.models import DebateRun, Judging
from llm_court.modes import DebateMode

VerdictLabel = str
"""affirmative / negative / draw。"""


def verdict_label(verdict: Verdict) -> VerdictLabel:
    return verdict.winner.value if verdict.winner else "draw"


def ratio(numerator: float, denominator: float) -> float | None:
    return numerator / denominator if denominator else None


def percentile(values: Sequence[float], q: float) -> float | None:
    """線形補間による分位点(q は 0〜1)。"""
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    low, high = math.floor(position), math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def mean(values: Iterable[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return statistics.fmean(present) if present else None


# --- 裁判長の一貫性 ---


def order_flip_rate(judgings: Iterable[Judging]) -> float | None:
    """提示順を入れ替えた評価の組のうち、勝者(合計点)が食い違った割合。"""
    pairs = [j for j in judgings if len(j.scores) == 2]
    flips = sum(j.scores[0].winner != j.scores[1].winner for j in pairs)
    return ratio(flips, len(pairs))


def repeat_stability(judgings: Sequence[Judging]) -> float | None:
    """同じログに対する判定が最頻の判定と一致した割合。判定が 2 回未満なら None。"""
    if len(judgings) < 2:
        return None
    labels = [verdict_label(j.verdict) for j in judgings]
    return Counter(labels).most_common(1)[0][1] / len(labels)


def margin_stdev(judgings: Iterable[Judging]) -> float | None:
    """各評価の点差(肯定側合計 − 否定側合計)の母標準偏差。評価が 2 回未満なら None。"""
    margins = [
        s.total(Side.AFFIRMATIVE) - s.total(Side.NEGATIVE) for j in judgings for s in j.scores
    ]
    return statistics.pstdev(margins) if len(margins) >= 2 else None


def self_judgings(run: DebateRun) -> list[Judging]:
    """ディベート中の判決と、同じ裁判長による再評価。"""
    return [j for j in run.judgings if j.source in ("debate", "repeat")]


def reference_agreement(runs: Iterable[DebateRun]) -> float | None:
    """ディベート中の判決が参照用裁判長の判決と一致した割合。"""
    pairs: list[tuple[str, str]] = []
    for run in runs:
        own = next((j for j in run.judgings if j.source == "debate"), None)
        ref = next((j for j in run.judgings if j.source == "reference"), None)
        if own and ref:
            pairs.append((verdict_label(own.verdict), verdict_label(ref.verdict)))
    return ratio(sum(a == b for a, b in pairs), len(pairs))


# --- 引用 ---


class CitationStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    statements: int = 0
    citations: int = 0
    unknown_evidence: int = 0
    checked_quotes: int = 0
    unsupported_quotes: int = 0
    no_citation: int = 0

    def __add__(self, other: "CitationStats") -> "CitationStats":
        return CitationStats(
            **{k: getattr(self, k) + getattr(other, k) for k in CitationStats.model_fields}
        )


def citation_stats(state: DebateState) -> CitationStats:
    """発言本文を現在の検査規則で検査し直して数える。

    イベントに記録された `CitationIssuesDetected` は記録時の規則による結果なので使わない
    (規則を直したとき、ディベートをやり直さずに過去の実行と比較できるようにするため)。
    """
    evidence = state.evidence_by_id
    kinds: Counter[str] = Counter()
    citations = 0
    checked = 0
    for s in state.statements:
        citations += len(extract_citations(s.text))
        checked += count_checked_quotes(s.text, evidence)
        kinds.update(i.kind for i in check_citations(s.id, s.text, evidence))
    return CitationStats(
        statements=len(state.statements),
        citations=citations,
        unknown_evidence=kinds["unknown_evidence"],
        checked_quotes=checked,
        unsupported_quotes=kinds["unsupported_quote"],
        no_citation=kinds["no_citation"],
    )


# --- 構成ごとの集計 ---


class RoleStructuredStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    calls: int
    failures: int
    retries: int


class ConfigMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    config: str
    debates: int
    completed: int
    aborted: int
    # 裁判長
    order_flip_rate: float | None
    repeat_stability: float | None
    margin_stdev: float | None
    reference_agreement: float | None
    verdicts: dict[str, int]
    # 引用
    citations: CitationStats
    unknown_evidence_rate: float | None
    """存在しない証拠品 ID ÷ 出典の総数。"""
    unsupported_quote_rate: float | None
    """証拠品にない引用 ÷ 照合対象の「」引用の総数。"""
    no_citation_rate: float | None
    """出典のない発言 ÷ 発言数。"""
    # 構造化出力
    structured_calls: int
    structured_failure_rate: float | None
    structured_retry_rate: float | None
    """構造化出力 1 回あたりの再試行数。"""
    structured_by_role: dict[str, RoleStructuredStats]
    # レイテンシ(秒)
    ttft_p50_s: float | None
    ttft_p90_s: float | None
    ttft_max_s: float | None
    turn_p50_s: float | None
    turn_p90_s: float | None
    turn_max_s: float | None
    tokens_per_s: float | None
    debate_mean_s: float | None
    # 補助
    mean_chars: float | None
    length_ratio: float | None
    """発言の字数 ÷ フェーズの目安字数 の平均。"""
    claims_per_statement: float | None


def _all_calls(runs: Iterable[DebateRun]) -> list[LLMCallInfo]:
    calls: list[LLMCallInfo] = []
    for run in runs:
        calls += DebateState.from_events(run.events).llm_calls
        calls += run.judge_calls
    return calls


def config_metrics(config: str, runs: Sequence[DebateRun], mode: DebateMode) -> ConfigMetrics:
    states = [DebateState.from_events(r.events) for r in runs]
    summaries = [summarize(r.events) for r in runs if r.events]
    completed = [r for r, s in zip(runs, states, strict=True) if s.verdict is not None]

    own_judgings = [j for r in completed for j in self_judgings(r)]
    stabilities = [repeat_stability(self_judgings(r)) for r in completed]
    margins = [margin_stdev(self_judgings(r)) for r in completed]

    citations = sum((citation_stats(s) for s in states), CitationStats())

    calls = _all_calls(runs)
    structured = [c for c in calls if c.kind == "structured"]
    by_role: dict[str, RoleStructuredStats] = {}
    for role in sorted({c.role for c in structured}):
        role_calls = [c for c in structured if c.role == role]
        by_role[role] = RoleStructuredStats(
            calls=len(role_calls),
            failures=sum(not c.success for c in role_calls),
            retries=sum(c.retries for c in role_calls),
        )

    turns = [t for s in summaries for t in s.turns]
    ttfts = [t.ttft_ms / 1000 for t in turns if t.ttft_ms is not None]
    totals = [t.total_ms / 1000 for t in turns if t.total_ms is not None]
    statements = [st for s in states for st in s.statements]

    return ConfigMetrics(
        config=config,
        debates=len(runs),
        completed=len(completed),
        aborted=len(runs) - len(completed),
        order_flip_rate=order_flip_rate(own_judgings),
        repeat_stability=mean(stabilities),
        margin_stdev=mean(margins),
        reference_agreement=reference_agreement(completed),
        verdicts=dict(Counter(verdict_label(s.verdict) for s in states if s.verdict is not None)),
        citations=citations,
        unknown_evidence_rate=ratio(citations.unknown_evidence, citations.citations),
        unsupported_quote_rate=ratio(citations.unsupported_quotes, citations.checked_quotes),
        no_citation_rate=ratio(citations.no_citation, citations.statements),
        structured_calls=len(structured),
        structured_failure_rate=ratio(sum(not c.success for c in structured), len(structured)),
        structured_retry_rate=ratio(sum(c.retries for c in structured), len(structured)),
        structured_by_role=by_role,
        ttft_p50_s=percentile(ttfts, 0.5),
        ttft_p90_s=percentile(ttfts, 0.9),
        ttft_max_s=max(ttfts, default=None),
        turn_p50_s=percentile(totals, 0.5),
        turn_p90_s=percentile(totals, 0.9),
        turn_max_s=max(totals, default=None),
        tokens_per_s=mean(t.tokens_per_s for t in turns),
        debate_mean_s=mean(s.wall_time_s for s in summaries),
        mean_chars=mean(len(st.text) for st in statements),
        length_ratio=mean(len(st.text) / mode.target_chars[st.phase] for st in statements),
        claims_per_statement=ratio(sum(len(s.claims) for s in states), len(statements)),
    )
