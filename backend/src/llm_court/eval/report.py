"""評価結果の CSV・Markdown レポート。"""

import csv
from collections.abc import Callable, Sequence
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from llm_court.domain import Side
from llm_court.engine.state import DebateState
from llm_court.engine.store import load_jsonl
from llm_court.engine.summary import summarize
from llm_court.eval.metrics import ConfigMetrics, citation_stats, config_metrics, verdict_label
from llm_court.eval.models import EvalResult
from llm_court.modes import DebateMode

_VERDICT_LABELS = {"affirmative": "肯定側", "negative": "否定側", "draw": "引き分け"}

Row = dict[str, object]


class ReportFiles(BaseModel):
    model_config = ConfigDict(frozen=True)

    runs_csv: Path
    turns_csv: Path
    summary_csv: Path
    markdown: Path
    result_json: Path


def run_rows(result: EvalResult) -> list[Row]:
    rows: list[Row] = []
    for run in result.runs:
        state = DebateState.from_events(run.events)
        summary = summarize(run.events) if run.events else None
        cites = citation_stats(state)
        verdict = state.verdict
        repeats = [verdict_label(j.verdict) for j in run.judgings if j.source == "repeat"]
        reference = next((j for j in run.judgings if j.source == "reference"), None)
        rows.append(
            {
                "config": run.config,
                "topic": run.topic,
                "run": run.run,
                "session_id": run.session_id,
                "status": "completed" if verdict else "aborted",
                "verdict": verdict_label(verdict) if verdict else "",
                "agreed": verdict.agreed if verdict else "",
                "affirmative_total": verdict.totals[Side.AFFIRMATIVE] if verdict else "",
                "negative_total": verdict.totals[Side.NEGATIVE] if verdict else "",
                "repeat_verdicts": ";".join(repeats),
                "reference_verdict": verdict_label(reference.verdict) if reference else "",
                "statements": cites.statements,
                "citations": cites.citations,
                "unknown_evidence": cites.unknown_evidence,
                "checked_quotes": cites.checked_quotes,
                "unsupported_quotes": cites.unsupported_quotes,
                "no_citation": cites.no_citation,
                "claims": len(state.claims),
                "llm_calls": (summary.llm_calls if summary else 0) + len(run.judge_calls),
                "input_tokens": summary.input_tokens if summary else 0,
                "output_tokens": summary.output_tokens if summary else 0,
                "wall_time_s": _round(summary.wall_time_s) if summary else "",
                "error": run.error or "",
            }
        )
    return rows


def turn_rows(result: EvalResult) -> list[Row]:
    rows: list[Row] = []
    for run in result.runs:
        if not run.events:
            continue
        for t in summarize(run.events).turns:
            rows.append(
                {
                    "config": run.config,
                    "topic": run.topic,
                    "run": run.run,
                    "session_id": run.session_id,
                    "statement_id": t.statement_id,
                    "side": t.side.value,
                    "phase": t.phase.value,
                    "round": t.round,
                    "chars": t.chars,
                    "ttft_s": _round(t.ttft_ms / 1000 if t.ttft_ms is not None else None),
                    "total_s": _round(t.total_ms / 1000 if t.total_ms is not None else None),
                    "output_tokens": t.output_tokens if t.output_tokens is not None else "",
                    "tokens_per_s": _round(t.tokens_per_s),
                }
            )
    return rows


def summary_rows(metrics: Sequence[ConfigMetrics]) -> list[Row]:
    rows: list[Row] = []
    for m in metrics:
        row: Row = {}
        for key, value in m.model_dump().items():
            if key in ("structured_by_role", "verdicts"):
                continue
            if key == "citations":
                row |= {f"citations_{k}": v for k, v in value.items()}
                continue
            row[key] = _round(value) if isinstance(value, float) else value
        for label in ("affirmative", "negative", "draw"):
            row[f"verdicts_{label}"] = m.verdicts.get(label, 0)
        rows.append(row)
    return rows


def _round(value: float | None, digits: int = 3) -> object:
    return "" if value is None else round(value, digits)


def _write_csv(path: Path, rows: list[Row]) -> None:
    fields: list[str] = []
    for row in rows:
        fields += [k for k in row if k not in fields]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


# --- Markdown ---


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{value:.0%}"


def _num(value: float | None, digits: int = 1) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def _sec(value: float | None) -> str:
    return "-" if value is None else f"{value:.1f}s"


MetricRow = tuple[str, Callable[[ConfigMetrics], str]]

_SECTIONS: list[tuple[str, list[MetricRow]]] = [
    (
        "実行",
        [
            ("ディベート数(完了 / 中断)", lambda m: f"{m.debates}({m.completed} / {m.aborted})"),
            (
                "判決(肯定 / 否定 / 引き分け)",
                lambda m: " / ".join(
                    str(m.verdicts.get(k, 0)) for k in ("affirmative", "negative", "draw")
                ),
            ),
        ],
    ),
    (
        "裁判長の一貫性",
        [
            ("順序反転率 ↓", lambda m: _pct(m.order_flip_rate)),
            ("再評価の安定性 ↑", lambda m: _pct(m.repeat_stability)),
            ("点差のばらつき(標準偏差)↓", lambda m: _num(m.margin_stdev)),
            ("参照用裁判長との一致率 ↑", lambda m: _pct(m.reference_agreement)),
        ],
    ),
    (
        "引用",
        [
            ("出典の総数", lambda m: str(m.citations.citations)),
            (
                "存在しない証拠品の率 ↓",
                lambda m: f"{_pct(m.unknown_evidence_rate)}({m.citations.unknown_evidence})",
            ),
            (
                "証拠品にない引用の率 ↓",
                lambda m: (
                    f"{_pct(m.unsupported_quote_rate)}"
                    f"({m.citations.unsupported_quotes}/{m.citations.checked_quotes})"
                ),
            ),
            ("出典のない発言の率 ↓", lambda m: _pct(m.no_citation_rate)),
        ],
    ),
    (
        "構造化出力",
        [
            ("呼び出し数", lambda m: str(m.structured_calls)),
            ("失敗率 ↓", lambda m: _pct(m.structured_failure_rate)),
            ("1 回あたりのリトライ ↓", lambda m: _num(m.structured_retry_rate, 2)),
        ],
    ),
    (
        "レイテンシ",
        [
            (
                "TTFT p50 / p90 / 最大",
                lambda m: " / ".join(_sec(v) for v in (m.ttft_p50_s, m.ttft_p90_s, m.ttft_max_s)),
            ),
            (
                "発言の総時間 p50 / p90 / 最大",
                lambda m: " / ".join(_sec(v) for v in (m.turn_p50_s, m.turn_p90_s, m.turn_max_s)),
            ),
            ("生成速度(tok/s 平均)", lambda m: _num(m.tokens_per_s)),
            ("ディベート 1 回の所要時間(平均)", lambda m: _sec(m.debate_mean_s)),
        ],
    ),
    (
        "発言",
        [
            ("平均字数", lambda m: _num(m.mean_chars, 0)),
            ("目安字数に対する比 → 1.0", lambda m: _num(m.length_ratio, 2)),
            ("発言あたりの主張数", lambda m: _num(m.claims_per_statement)),
        ],
    ),
]


def render_markdown(result: EvalResult, metrics: Sequence[ConfigMetrics]) -> str:
    names = [m.config for m in metrics]
    duration = (result.finished_at - result.started_at).total_seconds()
    lines = [
        f"# 評価レポート: {result.name}",
        "",
        f"- 実行: {result.started_at:%Y-%m-%d %H:%M} UTC(所要 {duration / 60:.0f} 分)",
        f"- 反論の往復: {result.rounds} / 裁判長の再評価: {result.judge_repeats} 回",
        f"- 参照用裁判長: {result.reference_judge or 'なし'}",
        "",
        "## 構成",
        "",
        "| 構成 | 論者 | 書記官 | 裁判長 |",
        "|---|---|---|---|",
    ]
    for name, roles in result.configs.items():
        lines.append(
            f"| {name} | {roles.get('debater', '-')} | "
            f"{roles.get('claim_extractor', '-')} | {roles.get('judge', '-')} |"
        )
    lines.append("")

    header = "| 指標 | " + " | ".join(names) + " |"
    divider = "|---|" + "---|" * len(names)
    lines += ["## 比較", "", "↑ は大きいほど良い、↓ は小さいほど良い。", ""]
    for title, rows in _SECTIONS:
        lines += [f"### {title}", "", header, divider]
        lines += [f"| {label} | " + " | ".join(fn(m) for m in metrics) + " |" for label, fn in rows]
        lines.append("")

    lines += ["### 役割別の構造化出力", "", "| 構成 | 役割 | 呼び出し | 失敗 | リトライ |"]
    lines.append("|---|---|---|---|---|")
    for m in metrics:
        for role, stats in m.structured_by_role.items():
            lines.append(
                f"| {m.config} | {role} | {stats.calls} | {stats.failures} | {stats.retries} |"
            )
    lines.append("")

    lines += [
        "## ディベートごとの結果",
        "",
        "| 構成 | テーマ | 回 | 判決 | 順序一致 | 再評価 | 参照 | 出典の問題 | 所要 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for row in run_rows(result):
        issues = int(str(row["unknown_evidence"])) + int(str(row["unsupported_quotes"]))
        issues += int(str(row["no_citation"]))
        verdict = _VERDICT_LABELS.get(str(row["verdict"]), "中断")
        repeats = " ".join(_VERDICT_LABELS[v] for v in str(row["repeat_verdicts"]).split(";") if v)
        reference = _VERDICT_LABELS.get(str(row["reference_verdict"]), "-")
        agreed = "○" if row["agreed"] is True else "×" if row["agreed"] is False else "-"
        wall = f"{row['wall_time_s']}s" if row["wall_time_s"] != "" else "-"
        lines.append(
            f"| {row['config']} | {row['topic']} | {row['run']} | {verdict} | {agreed} | "
            f"{repeats or '-'} | {reference} | {issues} | {wall} |"
        )
    lines.append("")

    lines += [
        "## 指標の定義",
        "",
        "- 順序反転率: 発言ブロックの提示順を入れ替えた 2 回の評価の組のうち、合計点による"
        "勝者が食い違った割合(ディベート中の判決と再評価の全組)",
        "- 再評価の安定性: 同じログに対する判定(ディベート中の判決+再評価)が"
        "最頻の判定と一致した割合の平均",
        "- 点差のばらつき: 同じログに対する各評価の(肯定側合計 − 否定側合計)の標準偏差の平均",
        "- 存在しない証拠品の率: 存在しない証拠品 ID の出典 ÷ 出典の総数",
        "- 証拠品にない引用の率: 出典付きの文の「」引用のうち、"
        "引いた証拠品の検証済み事実・要約に見つからないものの割合",
        "- 出典のない発言の率: 出典が 1 つもない発言 ÷ 発言数",
        "- レイテンシ: 論者の発言ごとの計測。TTFT は思考部分を含む最初のトークンまで",
        "",
        "## 注意",
        "",
        "- 証拠品は構成間で同じ捜査結果を使っている(捜査の性能は比較に含まない)",
        "- 各構成で論者と裁判長が同じモデルの場合、裁判長の自己選好バイアスが入りうる",
        f"- サンプル数はディベート {len(result.runs)} 回で、差の有意性は検定していない",
        "",
    ]
    return "\n".join(lines)


def load_result(out_dir: Path) -> EvalResult:
    """`write_report` で保存した結果を、debates/*.jsonl のイベントを付けて読み戻す。"""
    result = EvalResult.model_validate_json((out_dir / "result.json").read_text(encoding="utf-8"))
    runs = [
        run.model_copy(
            update={
                "events": load_jsonl(out_dir / "debates" / f"{run.config}-{run.session_id}.jsonl")
            }
        )
        for run in result.runs
    ]
    return result.model_copy(update={"runs": runs})


def compute_metrics(result: EvalResult, mode: DebateMode) -> list[ConfigMetrics]:
    return [
        config_metrics(name, [r for r in result.runs if r.config == name], mode)
        for name in result.configs
    ]


def write_report(
    result: EvalResult, metrics: Sequence[ConfigMetrics], out_dir: Path
) -> ReportFiles:
    out_dir.mkdir(parents=True, exist_ok=True)
    files = ReportFiles(
        runs_csv=out_dir / "runs.csv",
        turns_csv=out_dir / "turns.csv",
        summary_csv=out_dir / "summary.csv",
        markdown=out_dir / "report.md",
        result_json=out_dir / "result.json",
    )
    _write_csv(files.runs_csv, run_rows(result))
    _write_csv(files.turns_csv, turn_rows(result))
    _write_csv(files.summary_csv, summary_rows(metrics))
    files.markdown.write_text(render_markdown(result, metrics), encoding="utf-8")
    # イベントは debates/*.jsonl にあるので、結果 JSON からは除く
    files.result_json.write_text(
        result.model_dump_json(indent=2, exclude={"runs": {"__all__": {"events"}}}),
        encoding="utf-8",
    )
    return files
