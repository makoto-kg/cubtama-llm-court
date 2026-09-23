"""状態から人間が読める Markdown の法廷記録を作る。"""

from llm_court.domain import Side
from llm_court.engine.state import DebateState
from llm_court.modes import DebateMode

_ISSUE_LABELS = {
    "unknown_evidence": "存在しない証拠品",
    "unsupported_quote": "証拠品にない引用",
    "no_citation": "出典なし",
}
_KIND_LABELS = {"fact": "事実", "value": "価値判断", "inference": "推論"}


def render_markdown(state: DebateState, mode: DebateMode) -> str:
    lines: list[str] = [f"# 法廷記録: {state.topic}", ""]
    lines += [f"- セッション: `{state.session_id}`", f"- 反論の往復: {state.rounds}"]
    lines += [f"- {role}: {model}" for role, model in state.models.items()]
    lines.append("")

    lines += ["## 証拠品", ""]
    for ev in state.evidence:
        date = f"({ev.published_date})" if ev.published_date else ""
        lines += [f"### {ev.id} {ev.title}{date}", "", f"<{ev.source_url}>", "", ev.summary, ""]
        for fact in ev.key_facts:
            mark = "✓" if fact.quote_verified else "✗ 未検証"
            lines.append(f"- {mark} {fact.text} — 「{fact.quote}」")
        lines.append("")

    claims_by_statement: dict[str, list[str]] = {}
    for c in state.claims:
        ids = f" [{', '.join(c.cited_evidence_ids)}]" if c.cited_evidence_ids else ""
        claims_by_statement.setdefault(c.statement_id, []).append(
            f"- {c.id}({_KIND_LABELS[c.kind]}){c.text}{ids}"
        )
    issues_by_statement: dict[str, list[str]] = {}
    for i in state.citation_issues:
        issues_by_statement.setdefault(i.statement_id, []).append(
            f"- ⚠ {_ISSUE_LABELS[i.kind]}: {i.detail}"
        )

    lines += ["## 弁論", ""]
    heading: str | None = None
    for s in state.statements:
        phase_heading = s.phase.label + (f" 第{s.round}回" if s.round else "")
        if phase_heading != heading:
            heading = phase_heading
            lines += [f"### {heading}", ""]
        lines += [f"#### {s.id} {s.side.label}", "", s.text, ""]
        if s.id in issues_by_statement:
            lines += ["出典の問題:", "", *issues_by_statement[s.id], ""]
        if s.id in claims_by_statement:
            lines += ["主張:", "", *claims_by_statement[s.id], ""]

    if state.judge_scores:
        lines += ["## 採点", ""]
        header = "| 評価 | 提示順 | 陣営 | " + " | ".join(c.name for c in mode.rubric) + " | 合計 |"
        lines += [header, "|" + "---|" * (len(mode.rubric) + 4)]
        for n, score in enumerate(state.judge_scores, start=1):
            order = " → ".join(side.label for side in score.order)
            for side in Side:
                cells = " | ".join(str(score.scores[side][c.key]) for c in mode.rubric)
                lines.append(f"| {n} | {order} | {side.label} | {cells} | {score.total(side)} |")
        lines.append("")

    if state.verdict:
        v = state.verdict
        result = f"{v.winner.label}の勝ち" if v.winner else "引き分け"
        note = "" if v.agreed else "(順序を入れ替えた評価で勝者が一致しなかったため)"
        totals = " / ".join(f"{side.label} {v.totals[side]:.1f} 点" for side in Side)
        lines += ["## 判決", "", f"**{result}**{note}", "", f"平均合計点: {totals}", ""]
        lines += [v.rationale, ""]
    elif state.aborted:
        lines += ["## 中断", "", state.aborted, ""]
    return "\n".join(lines)
