"""各段階の LLM 出力(下書き)のスキーマと、ドメインモデルへの変換。

LLM には自由な下書きのキー(人物なら p1 など)で互いを参照させ、正式な ID の採番と参照の
組み立てはコードで行う。参照が解決できなければ `DraftError` にして、問題点を伝えて作り直す。
"""

import re
from collections.abc import Sequence

from pydantic import BaseModel, Field

from llm_court.domain import (
    CaseEvidence,
    CaseQuestion,
    CollapseCondition,
    Contradiction,
    Evidence,
    HiddenTruth,
    LearningPoint,
    LearningSource,
    Lie,
    Person,
    Testimony,
    TestimonyLine,
    TimelineEvent,
    Trap,
    WitnessScript,
    normalize_evidence_ids,
)


class DraftError(ValueError):
    """下書きの参照が解決できない。`problems` を作り直しのフィードバックに使う。"""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def fact_key(evidence_id: str, index: int) -> str:
    """プロンプトに示す検証済み事実のキー(例: EV-01-f2)。"""
    return f"{evidence_id}-f{index}"


_FACT_KEY = re.compile(r"(EV-\d+)-f(\d+)", re.IGNORECASE)


def replace_keys(text: str, names: dict[str, str]) -> str:
    """文中に残った下書きのキー(p2・e1 など)を、名前や正式な ID に置き換える。"""
    if not names:
        return text
    pattern = re.compile(
        r"(?<![A-Za-z0-9])(" + "|".join(map(re.escape, names)) + r")(?![A-Za-z0-9])"
    )
    return pattern.sub(lambda m: names[m.group(1)], text)


# --- 1. 学習ポイント ---


class LearningPointDraft(BaseModel):
    knowledge: str = Field(min_length=5)
    explanation: str = Field(min_length=5)
    fact_keys: list[str] = Field(min_length=1, description="根拠の検証済み事実のキー(例: EV-01-f1)")
    misconception: str = Field(min_length=5)
    outdated: bool = False
    outdated_belief: str | None = None


class LearningPointsOutput(BaseModel):
    points: list[LearningPointDraft] = Field(min_length=1, max_length=5)


def to_learning_points(
    output: LearningPointsOutput, evidence: Sequence[Evidence], limit: int
) -> list[LearningPoint]:
    """出典を検証済みの事実に結び付ける。照合できない出典は捨て、出典がなくなった点は除く。"""
    by_id = {e.id: e for e in evidence}
    points: list[LearningPoint] = []
    problems: list[str] = []
    for draft in output.points:
        sources: list[LearningSource] = []
        for key in draft.fact_keys:
            match = _FACT_KEY.search(key)
            ids = normalize_evidence_ids([match.group(1)]) if match else []
            ev = by_id.get(ids[0]) if ids else None
            facts = ev.verified_facts if ev else []
            index = int(match.group(2)) if match else 0
            if ev is None or not 1 <= index <= len(facts):
                problems.append(
                    f"「{draft.knowledge[:20]}」の出典 {key} は検証済みの事実にありません"
                )
                continue
            fact = facts[index - 1]
            sources.append(
                LearningSource(
                    evidence_id=ev.id, title=ev.title, url=ev.source_url, quote=fact.quote
                )
            )
        if not sources:
            continue
        points.append(
            LearningPoint(
                id=f"LP-{len(points) + 1:02d}",
                knowledge=draft.knowledge,
                explanation=draft.explanation,
                sources=sources,
                misconception=draft.misconception,
                outdated=draft.outdated,
                outdated_belief=draft.outdated_belief if draft.outdated else None,
            )
        )
        if len(points) >= limit:
            break
    if len(points) < 2:
        raise DraftError([*problems, "出典を確認できる学習ポイントが 2 つ未満です"])
    return points


# --- 2. 真相 ---


class PersonDraft(BaseModel):
    key: str = Field(min_length=1)
    name: str = Field(min_length=1)
    role: str = Field(min_length=1)
    description: str = Field(min_length=1)


class TimelineDraft(BaseModel):
    key: str = Field(min_length=1)
    order: int
    time: str
    location: str
    person_keys: list[str]
    description: str = Field(min_length=1)


class LieDraft(BaseModel):
    witness_key: str
    false_claim: str = Field(min_length=5)
    truth_event_key: str
    learning_point_ids: list[str] = Field(min_length=1)


class HiddenTruthOutput(BaseModel):
    summary: str = Field(min_length=10)
    people: list[PersonDraft] = Field(min_length=2)
    timeline: list[TimelineDraft] = Field(min_length=3)
    lies: list[LieDraft] = Field(min_length=1)


def to_hidden_truth(
    output: HiddenTruthOutput, learning_points: Sequence[LearningPoint]
) -> tuple[list[Person], HiddenTruth]:
    problems: list[str] = []
    person_ids = {p.key: f"P-{i:02d}" for i, p in enumerate(output.people, start=1)}
    people = [
        Person(id=person_ids[p.key], name=p.name, role=p.role, description=p.description)
        for p in output.people
    ]
    ordered = sorted(output.timeline, key=lambda t: t.order)
    event_ids = {t.key: f"T-{i:02d}" for i, t in enumerate(ordered, start=1)}
    timeline: list[TimelineEvent] = []
    for t in ordered:
        unknown = [k for k in t.person_keys if k not in person_ids]
        if unknown:
            problems.append(f"時系列 {t.key} の人物 {unknown} が人物一覧にありません")
        timeline.append(
            TimelineEvent(
                id=event_ids[t.key],
                order=t.order,
                time=t.time,
                location=t.location,
                person_ids=[person_ids[k] for k in t.person_keys if k in person_ids],
                description=t.description,
            )
        )
    lp_ids = {lp.id for lp in learning_points}
    lies: list[Lie] = []
    for i, draft in enumerate(output.lies, start=1):
        if draft.witness_key not in person_ids:
            problems.append(f"嘘 {i} の証人 {draft.witness_key} が人物一覧にありません")
            continue
        if draft.truth_event_key not in event_ids:
            problems.append(f"嘘 {i} の実際の出来事 {draft.truth_event_key} が時系列にありません")
            continue
        refs = [lp for lp in draft.learning_point_ids if lp in lp_ids]
        if not refs:
            problems.append(f"嘘 {i} が既知の学習ポイント({sorted(lp_ids)})を参照していません")
            continue
        lies.append(
            Lie(
                id=f"L-{len(lies) + 1:02d}",
                witness_id=person_ids[draft.witness_key],
                false_claim=draft.false_claim,
                truth_event_id=event_ids[draft.truth_event_key],
                learning_point_ids=refs,
            )
        )
    used = {lp for lie in lies for lp in lie.learning_point_ids}
    for lp_id in sorted(lp_ids - used):
        problems.append(
            f"学習ポイント {lp_id} を見抜くのに使う嘘がありません(すべての学習ポイントを使う)"
        )
    if problems:
        raise DraftError(problems)
    names = {p.key: p.name for p in output.people}
    summary = replace_keys(output.summary, names)
    lies = [
        lie.model_copy(update={"false_claim": replace_keys(lie.false_claim, names)}) for lie in lies
    ]
    return people, HiddenTruth(summary=summary, timeline=timeline, lies=lies)


# --- 3. 資料(証拠品・証言・台本・矛盾・問い) ---


class EvidenceDraft(BaseModel):
    key: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    details: list[str] = Field(min_length=1)


class TestimonyLineDraft(BaseModel):
    text: str = Field(min_length=1)
    lie_id: str | None = None


class TestimonyDraft(BaseModel):
    witness_id: str
    title: str = Field(min_length=1)
    lines: list[TestimonyLineDraft] = Field(min_length=2)


class ScriptDraft(BaseModel):
    witness_id: str
    persona: str = Field(min_length=1)
    hidden_facts: list[str]


class ContradictionDraft(BaseModel):
    lie_id: str
    evidence_key: str
    learning_point_ids: list[str] = Field(min_length=1)
    explanation: str = Field(min_length=10)
    witness_reaction: str = Field(
        min_length=1, description="証拠品をつきつけられて嘘が崩れたときの証人の反応"
    )


class QuestionDraft(BaseModel):
    text: str = Field(min_length=5)
    options: list[str] = Field(min_length=2, max_length=5)
    answer_index: int = Field(ge=0)


class MaterialsOutput(BaseModel):
    title: str = Field(min_length=1)
    overview: str = Field(min_length=10)
    question: QuestionDraft
    evidence: list[EvidenceDraft] = Field(min_length=2)
    testimonies: list[TestimonyDraft] = Field(min_length=1)
    scripts: list[ScriptDraft] = Field(min_length=1)
    contradictions: list[ContradictionDraft] = Field(min_length=1)


class Materials(BaseModel):
    title: str
    overview: str
    question: CaseQuestion
    evidence: list[CaseEvidence]
    testimonies: list[Testimony]
    witness_scripts: list[WitnessScript]
    contradictions: list[Contradiction]


def to_materials(
    output: MaterialsOutput,
    people: Sequence[Person],
    truth: HiddenTruth,
    learning_points: Sequence[LearningPoint],
) -> Materials:
    problems: list[str] = []
    person_ids = {p.id for p in people}
    lie_by_id = {lie.id: lie for lie in truth.lies}
    lp_ids = {lp.id for lp in learning_points}
    evidence_ids = {e.key: f"CE-{i:02d}" for i, e in enumerate(output.evidence, start=1)}
    evidence = [
        CaseEvidence(
            id=evidence_ids[e.key], name=e.name, description=e.description, details=e.details
        )
        for e in output.evidence
    ]

    testimonies: list[Testimony] = []
    for i, t in enumerate(output.testimonies, start=1):
        if t.witness_id not in person_ids:
            problems.append(f"証言 {i} の証人 {t.witness_id} が人物一覧にありません")
        lines: list[TestimonyLine] = []
        for j, line in enumerate(t.lines, start=1):
            if line.lie_id is not None and line.lie_id not in lie_by_id:
                problems.append(f"証言 {i} の {j} 行目の嘘 {line.lie_id} が真相にありません")
            lines.append(
                TestimonyLine(
                    id=f"TS-{i:02d}-{j}",
                    text=line.text,
                    lie_id=line.lie_id if line.lie_id in lie_by_id else None,
                )
            )
        testimonies.append(
            Testimony(id=f"TS-{i:02d}", witness_id=t.witness_id, title=t.title, lines=lines)
        )
    line_by_lie = {
        line.lie_id: line.id for t in testimonies for line in t.lines if line.lie_id is not None
    }

    # 各嘘がちょうど 1 行・1 件の矛盾に対応しているか(ここで検出して、この段階だけ作り直す)
    lie_line_count = {lie_id: 0 for lie_id in lie_by_id}
    for t in testimonies:
        for line in t.lines:
            if line.lie_id is not None:
                lie_line_count[line.lie_id] += 1
    for lie_id, count in lie_line_count.items():
        if count != 1:
            problems.append(f"嘘 {lie_id} を含む証言の行が {count} 行あります(ちょうど 1 行にする)")
    per_lie: dict[str, int] = {lie_id: 0 for lie_id in lie_by_id}
    for c in output.contradictions:
        if c.lie_id in per_lie:
            per_lie[c.lie_id] += 1
    for lie_id, count in per_lie.items():
        if count != 1:
            problems.append(f"嘘 {lie_id} の矛盾が {count} 件あります(嘘ごとにちょうど 1 件にする)")

    contradictions: list[Contradiction] = []
    reactions: dict[str, str] = {}
    for c in output.contradictions:
        if c.lie_id not in line_by_lie:
            problems.append(f"矛盾の嘘 {c.lie_id} を含む証言の行がありません")
            continue
        if c.evidence_key not in evidence_ids:
            problems.append(f"矛盾 {c.lie_id} の証拠品 {c.evidence_key} が証拠品一覧にありません")
            continue
        # 嘘に設定した学習ポイントを必ず引き継ぐ(資料の段階で書き漏れても対応が崩れないように)
        lie_lps = lie_by_id[c.lie_id].learning_point_ids if c.lie_id in lie_by_id else []
        refs = list(dict.fromkeys([*lie_lps, *(lp for lp in c.learning_point_ids if lp in lp_ids)]))
        if not refs:
            problems.append(f"矛盾 {c.lie_id} が既知の学習ポイントを参照していません")
            continue
        reactions[c.lie_id] = c.witness_reaction
        contradictions.append(
            Contradiction(
                id=f"X-{len(contradictions) + 1:02d}",
                testimony_line_id=line_by_lie[c.lie_id],
                evidence_id=evidence_ids[c.evidence_key],
                lie_id=c.lie_id,
                learning_point_ids=refs,
                explanation=replace_keys(c.explanation, evidence_ids),
            )
        )

    # 台本の崩れる条件は矛盾から組み立てる(証拠品と反応を二重に書かせない)
    scripts: list[WitnessScript] = []
    for script in output.scripts:
        if script.witness_id not in person_ids:
            problems.append(f"台本の証人 {script.witness_id} が人物一覧にありません")
            continue
        lie_ids = [lie.id for lie in truth.lies if lie.witness_id == script.witness_id]
        scripts.append(
            WitnessScript(
                witness_id=script.witness_id,
                persona=script.persona,
                hidden_facts=script.hidden_facts,
                lie_ids=lie_ids,
                collapse_conditions=[
                    CollapseCondition(
                        lie_id=c.lie_id, evidence_id=c.evidence_id, reaction=reactions[c.lie_id]
                    )
                    for c in contradictions
                    if c.lie_id in lie_ids
                ],
            )
        )

    q = output.question
    if not 0 <= q.answer_index < len(q.options):
        problems.append(f"問いの正解の番号 {q.answer_index} が選択肢の範囲外です")
    if problems:
        raise DraftError(problems)
    return Materials(
        title=output.title,
        overview=output.overview,
        question=CaseQuestion(text=q.text, options=q.options, answer_index=q.answer_index),
        evidence=evidence,
        testimonies=testimonies,
        witness_scripts=scripts,
        contradictions=contradictions,
    )


# --- 4. 罠 ---


class TrapDraft(BaseModel):
    contradiction_id: str
    evidence_id: str
    reasoning: str = Field(min_length=5)
    learning_point_id: str
    why_tempting: str = Field(min_length=5)


class TrapsOutput(BaseModel):
    traps: list[TrapDraft] = Field(min_length=1)


def attach_traps(
    output: TrapsOutput,
    contradictions: Sequence[Contradiction],
    evidence: Sequence[CaseEvidence],
    learning_points: Sequence[LearningPoint],
    per_contradiction: int,
) -> list[Contradiction]:
    evidence_ids = {e.id for e in evidence}
    lp_ids = {lp.id for lp in learning_points}
    by_contradiction: dict[str, list[Trap]] = {c.id: [] for c in contradictions}
    answer = {c.id: c.evidence_id for c in contradictions}
    problems: list[str] = []
    for draft in output.traps:
        where = f"罠({draft.contradiction_id}, {draft.evidence_id})"
        if draft.contradiction_id not in by_contradiction:
            problems.append(f"{where}: 矛盾の ID は {sorted(by_contradiction)} のいずれかにする")
        elif draft.evidence_id not in evidence_ids:
            problems.append(f"{where}: 証拠品の ID は {sorted(evidence_ids)} のいずれかにする")
        elif draft.evidence_id == answer[draft.contradiction_id]:
            problems.append(f"{where}: 正解の証拠品は罠に使えない")
        elif draft.learning_point_id not in lp_ids:
            problems.append(f"{where}: 学習ポイントの ID は {sorted(lp_ids)} のいずれかにする")
        elif len(by_contradiction[draft.contradiction_id]) < per_contradiction:
            by_contradiction[draft.contradiction_id].append(
                Trap(
                    evidence_id=draft.evidence_id,
                    reasoning=draft.reasoning,
                    learning_point_id=draft.learning_point_id,
                    why_tempting=draft.why_tempting,
                )
            )
    missing = [cid for cid, traps in by_contradiction.items() if not traps]
    if missing:
        raise DraftError(
            problems
            + [f"矛盾 {cid} に有効な罠がありません(正解以外の証拠品を使うこと)" for cid in missing]
        )
    return [c.model_copy(update={"traps": by_contradiction[c.id]}) for c in contradictions]
