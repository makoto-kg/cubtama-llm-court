"""事件の規則ベースの整合性チェック。

問題ごとに作り直す段階(`step`)を付ける。生成パイプラインは最も早い段階から作り直す。
"""

import re
from collections import Counter, defaultdict

from llm_court.domain import Case, CheckIssue
from llm_court.modes import TrialMode

STEP_ORDER = ("learning_points", "hidden_truth", "materials", "traps")


def earliest_step(issues: list[CheckIssue]) -> str | None:
    steps = {i.step for i in issues}
    return next((s for s in STEP_ORDER if s in steps), None)


def check_case(case: Case, mode: TrialMode) -> list[CheckIssue]:
    issues: list[CheckIssue] = []

    def add(code: str, message: str, step: str) -> None:
        issues.append(CheckIssue(code=code, message=message, step=step))

    people = {p.id for p in case.people}
    events = {e.id: e for e in case.hidden_truth.timeline}
    lies = {lie.id: lie for lie in case.hidden_truth.lies}
    evidence = {e.id for e in case.evidence}
    lines = case.testimony_lines
    lps = {lp.id for lp in case.learning_points}

    # --- 真相(人物・時系列・嘘) ---
    orders = Counter(e.order for e in case.hidden_truth.timeline)
    for order, count in orders.items():
        if count > 1:
            add("timeline_order", f"時系列の順番 {order} が {count} 件あります", "hidden_truth")
    at: dict[tuple[str, str], set[str]] = defaultdict(set)
    for e in case.hidden_truth.timeline:
        for pid in e.person_ids:
            if pid not in people:
                add("missing_person", f"時系列 {e.id} の人物 {pid} がいません", "hidden_truth")
            at[(pid, e.time)].add(e.location)
    for (pid, time), locations in at.items():
        if len(locations) > 1:
            add(
                "timeline_conflict",
                f"{pid} が {time} に複数の場所({'、'.join(sorted(locations))})にいます",
                "hidden_truth",
            )
    lo, hi = mode.lies
    if not lo <= len(lies) <= hi:
        add("lie_count", f"嘘の数が {len(lies)} です({lo}〜{hi} 個にする)", "hidden_truth")
    for lie in lies.values():
        if lie.witness_id not in people:
            add("missing_person", f"嘘 {lie.id} の証人 {lie.witness_id} がいません", "hidden_truth")
        if lie.truth_event_id not in events:
            add("missing_event", f"嘘 {lie.id} の実際の出来事がありません", "hidden_truth")
        for lp in lie.learning_point_ids:
            if lp not in lps:
                add(
                    "missing_learning_point",
                    f"嘘 {lie.id} の学習ポイント {lp} がありません",
                    "hidden_truth",
                )

    # --- 資料(証言・台本・矛盾・問い) ---
    for t in case.testimonies:
        if t.witness_id not in people:
            add("missing_person", f"証言 {t.id} の証人 {t.witness_id} がいません", "materials")
    lie_lines = Counter(line.lie_id for line in lines.values() if line.lie_id)
    for lie_id in lies:
        if lie_lines[lie_id] != 1:
            add(
                "lie_line",
                f"嘘 {lie_id} を含む証言の行が {lie_lines[lie_id]} 行あります(1 行にする)",
                "materials",
            )
    by_lie = Counter(c.lie_id for c in case.contradictions)
    for lie_id in lies:
        if by_lie[lie_id] != 1:
            add(
                "lie_contradiction",
                f"嘘 {lie_id} に対応する矛盾が {by_lie[lie_id]} 件あります(1 件にする)",
                "materials",
            )
    for c in case.contradictions:
        line = lines.get(c.testimony_line_id)
        if line is None:
            add("missing_line", f"矛盾 {c.id} の証言の行がありません", "materials")
        elif line.lie_id != c.lie_id:
            add(
                "line_lie_mismatch",
                f"矛盾 {c.id} の証言の行が嘘 {c.lie_id} を含みません",
                "materials",
            )
        if c.evidence_id not in evidence:
            add(
                "missing_evidence",
                f"矛盾 {c.id} の証拠品 {c.evidence_id} がありません",
                "materials",
            )
        if not set(c.learning_point_ids) & lps:
            add("contradiction_without_lp", f"矛盾 {c.id} に学習ポイントがありません", "materials")
    used = {lp for c in case.contradictions for lp in c.learning_point_ids}
    for lp in sorted(lps - used):
        add(
            "unused_learning_point",
            f"学習ポイント {lp} がどの矛盾にも使われていません",
            "materials",
        )
    conditions = {
        (cond.lie_id, cond.evidence_id)
        for script in case.witness_scripts
        for cond in script.collapse_conditions
    }
    for c in case.contradictions:
        if (c.lie_id, c.evidence_id) not in conditions:
            add(
                "missing_collapse",
                f"嘘 {c.lie_id} の台本に、証拠品 {c.evidence_id} で崩れる条件がありません",
                "materials",
            )
    scripted = {s.witness_id for s in case.witness_scripts}
    for lie in lies.values():
        if lie.witness_id not in scripted:
            add("missing_script", f"証人 {lie.witness_id} の台本がありません", "materials")
    q = case.question
    if not 0 <= q.answer_index < len(q.options):
        add("question_answer", "問いの正解が選択肢の範囲外です", "materials")

    # 公開する文に非公開の ID が入っていないか
    pattern = re.compile(mode.public_id_pattern)
    public_texts = [case.overview, q.text, *q.options]
    public_texts += [line.text for line in lines.values()]
    public_texts += [e.description for e in case.evidence] + [
        d for e in case.evidence for d in e.details
    ]
    for text in public_texts:
        if pattern.search(text):
            add("public_leak", f"公開する文に非公開の ID があります: 「{text[:40]}」", "materials")

    # --- 罠 ---
    for c in case.contradictions:
        if not c.traps:
            add("missing_trap", f"矛盾 {c.id} に罠がありません", "traps")
        for trap in c.traps:
            if trap.evidence_id == c.evidence_id:
                add("trap_is_answer", f"矛盾 {c.id} の罠が正解の証拠品です", "traps")
            if trap.evidence_id not in evidence or trap.learning_point_id not in lps:
                add("trap_reference", f"矛盾 {c.id} の罠の参照が不正です", "traps")
    return issues
