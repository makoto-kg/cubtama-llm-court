"""閉廷後の解説を、事件のデータだけから組み立てる。

LLM に書かせないのは、出典のない説明を混ぜないため。学習ポイントの出典は事件生成時に
引用検証を通ったものだけが入っている。
"""

from llm_court.domain import Case, Explanation, ExplanationItem, ExplanationTrap


def build_explanation(case: Case) -> Explanation:
    people = {p.id: p.name for p in case.people}
    evidence = {e.id: e.name for e in case.evidence}
    lps = {lp.id: lp for lp in case.learning_points}
    witness_of = {line.id: t.witness_id for t in case.testimonies for line in t.lines}
    lines = case.testimony_lines
    items = [
        ExplanationItem(
            contradiction_id=c.id,
            witness_name=people.get(witness_of.get(c.testimony_line_id, ""), "被告"),
            testimony_line_id=c.testimony_line_id,
            testimony_line=lines[c.testimony_line_id].text,
            evidence_id=c.evidence_id,
            evidence_name=evidence.get(c.evidence_id, c.evidence_id),
            explanation=c.explanation,
            learning_point_ids=c.learning_point_ids,
            traps=[
                ExplanationTrap(
                    evidence_id=t.evidence_id,
                    evidence_name=evidence.get(t.evidence_id, t.evidence_id),
                    reasoning=t.reasoning,
                    why_tempting=t.why_tempting,
                    learning_point_id=t.learning_point_id,
                    misconception=lps[t.learning_point_id].misconception
                    if t.learning_point_id in lps
                    else "",
                )
                for t in c.traps
            ],
        )
        for c in case.contradictions
        if c.testimony_line_id in lines
    ]
    return Explanation(
        title=case.title,
        truth=case.hidden_truth.summary,
        question=case.question.text,
        answer=case.question.options[case.question.answer_index],
        items=items,
        learning_points=case.learning_points,
        verdict=case.verdict,
    )
