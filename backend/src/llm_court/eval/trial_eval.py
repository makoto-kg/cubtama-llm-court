"""証人の台本逸脱率の評価(`llm-court eval-trial`)。

決まった方針の自動プレイヤーで事件を最後まで遊び、証人に一通りの場面(ゆさぶり・
はずれ・罠・正解)を経験させて、判定役の逸脱の判定を集計する。
- 自白の早すぎ率: 崩れるべきでない応答のうち、自白した割合
- 崩れ損ね率: 崩れるべき応答のうち、崩れなかった割合
- 漏洩率: 崩れるべきでない応答のうち、隠している事実を漏らした割合
- 全体の逸脱率: 判定できた応答のうち、いずれかの逸脱があった割合
"""

import csv
from collections.abc import Callable, Sequence
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from llm_court.domain import (
    Case,
    Event,
    LLMCallRecorded,
    TrialChoiceMade,
    TrialOption,
    WitnessResponded,
)
from llm_court.engine.trial import TrialEngine
from llm_court.engine.trial_state import TrialState

ProgressFn = Callable[[str], None]


class ScriptedPlayer:
    """証言ごとに、ゆさぶる(すべての行)→ はずれ 1 回 → 罠 1 回 → 正解 の順に選ぶ。

    はずれ・罠でゲージが尽きないよう、評価ではゲージを大きくしたモードで使う。
    """

    def pick(self, state: TrialState) -> TrialOption:
        pending = state.pending_choices
        assert pending is not None
        options = pending.options
        tried_here = [c.option for c in state.choices if c.option.line_id in self._lines(state)]

        def first(pred: Callable[[TrialOption], bool]) -> TrialOption | None:
            return next((o for o in options if pred(o)), None)

        probe = first(lambda o: o.kind == "probe")
        if probe is not None:
            return probe
        for strength in ("weak", "trap"):
            if not any(o.strength == strength for o in tried_here):
                option = first(lambda o, s=strength: o.strength == s)
                if option is not None:
                    return option
        strong = first(lambda o: o.strength == "strong")
        return strong or options[0]

    @staticmethod
    def _lines(state: TrialState) -> set[str]:
        testimony = state.testimony
        return {line.id for line in testimony.lines} if testimony else set()


async def play_scripted(engine: TrialEngine, case: Case, *, max_steps: int = 60) -> TrialState:
    """自動プレイヤーで閉廷まで遊ぶ。最後の問いには正答する(問いは評価の対象外)。"""
    player = ScriptedPlayer()
    await engine.start(case)
    for _ in range(max_steps):
        state = engine.state
        match state.stage:
            case "choosing":
                await engine.choose(player.pick(state).id)
            case "answering":
                await engine.answer(case.question.answer_index)
            case "examining":
                await engine.advance()
            case _:
                break
    return engine.state


class ResponseRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    case_id: str
    run: int
    session_id: str
    option_id: str
    action: str
    """probe / weak / trap / strong。"""
    label: str
    should_collapse: bool
    checked: bool
    confessed: bool | None
    leaked: int
    deviations: list[str]
    reason: str
    text: str
    witness_ms: float | None


def response_rows(case_id: str, run: int, events: Sequence[Event]) -> list[ResponseRow]:
    options = {e.option.id: e.option for e in events if isinstance(e, TrialChoiceMade)}
    calls = {e.call.call_id: e.call.total_ms for e in events if isinstance(e, LLMCallRecorded)}
    rows: list[ResponseRow] = []
    for e in events:
        if not isinstance(e, WitnessResponded):
            continue
        option = options[e.option_id]
        check = e.check
        rows.append(
            ResponseRow(
                case_id=case_id,
                run=run,
                session_id=e.session_id,
                option_id=e.option_id,
                action=option.strength or option.kind,
                label=option.label,
                should_collapse=e.should_collapse,
                checked=check is not None,
                confessed=check.confessed if check else None,
                leaked=len(check.leaked_fact_indices) if check else 0,
                deviations=list(check.deviations) if check else [],
                reason=check.reason if check else "",
                text=e.text,
                witness_ms=calls.get(e.call_id or ""),
            )
        )
    return rows


class DeviationMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    scope: str
    responses: int
    checked: int
    premature_confession_rate: float | None
    failed_collapse_rate: float | None
    leak_rate: float | None
    deviation_rate: float | None
    witness_p50_s: float | None


def _rate(n: int, d: int) -> float | None:
    return n / d if d else None


def deviation_metrics(scope: str, rows: Sequence[ResponseRow]) -> DeviationMetrics:
    checked = [r for r in rows if r.checked]
    hold = [r for r in checked if not r.should_collapse]
    collapse = [r for r in checked if r.should_collapse]
    times = sorted(r.witness_ms for r in rows if r.witness_ms is not None)
    return DeviationMetrics(
        scope=scope,
        responses=len(rows),
        checked=len(checked),
        premature_confession_rate=_rate(
            sum("premature_confession" in r.deviations for r in hold), len(hold)
        ),
        failed_collapse_rate=_rate(
            sum("failed_collapse" in r.deviations for r in collapse), len(collapse)
        ),
        leak_rate=_rate(sum("leak" in r.deviations for r in hold), len(hold)),
        deviation_rate=_rate(sum(bool(r.deviations) for r in checked), len(checked)),
        witness_p50_s=times[len(times) // 2] / 1000 if times else None,
    )


def summarize_rows(rows: Sequence[ResponseRow]) -> list[DeviationMetrics]:
    """全体・事件ごと・行動ごとの指標。"""
    metrics = [deviation_metrics("全体", rows)]
    for case_id in dict.fromkeys(r.case_id for r in rows):
        metrics.append(
            deviation_metrics(f"事件 {case_id}", [r for r in rows if r.case_id == case_id])
        )
    for action in ("probe", "weak", "trap", "strong"):
        subset = [r for r in rows if r.action == action]
        if subset:
            metrics.append(deviation_metrics(f"行動 {action}", subset))
    return metrics


def _pct(v: float | None) -> str:
    return "-" if v is None else f"{v:.0%}"


def write_trial_report(
    out_dir: Path,
    rows: Sequence[ResponseRow],
    metrics: Sequence[DeviationMetrics],
    *,
    models: dict[str, str],
    failures: Sequence[str] = (),
) -> Path:
    """responses.csv・summary.csv・report.md を書き、Markdown のパスを返す。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "responses.csv").open("w", encoding="utf-8", newline="") as f:
        fields = list(ResponseRow.model_fields)
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for r in rows:
            data = r.model_dump()
            data["deviations"] = ";".join(r.deviations)
            writer.writerow(data)
    with (out_dir / "summary.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(DeviationMetrics.model_fields))
        writer.writeheader()
        for m in metrics:
            writer.writerow(m.model_dump())

    lines = [
        "# 証人の台本逸脱率",
        "",
        "モデル: " + ", ".join(f"{k}={v}" for k, v in sorted(models.items())),
        "",
        "| 範囲 | 応答 | 判定済み | 自白の早すぎ ↓ | 崩れ損ね ↓ | 漏洩 ↓ | 逸脱(全体)↓ "
        "| 応答 p50 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for m in metrics:
        p50 = "-" if m.witness_p50_s is None else f"{m.witness_p50_s:.1f}s"
        lines.append(
            f"| {m.scope} | {m.responses} | {m.checked} | {_pct(m.premature_confession_rate)} "
            f"| {_pct(m.failed_collapse_rate)} | {_pct(m.leak_rate)} "
            f"| {_pct(m.deviation_rate)} | {p50} |"
        )
    deviated = [r for r in rows if r.deviations]
    if deviated:
        lines += ["", "## 逸脱した応答", ""]
        for r in deviated:
            lines += [
                f"- **{r.case_id} #{r.run} {r.option_id}**({r.action}、{', '.join(r.deviations)})"
                f" {r.label}",
                f"  - 応答: {r.text}",
                f"  - 判定: {r.reason}",
            ]
    if failures:
        lines += ["", "## 完走できなかった実行", ""]
        lines += [f"- {f}" for f in failures]
    path = out_dir / "report.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
