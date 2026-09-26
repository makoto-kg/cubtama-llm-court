"""裁判型の事件(架空の事件・真相・証拠品・証言・台本・矛盾・学習ポイント)。

`Case` は非公開の情報(真相・台本・矛盾・正解・学習ポイント)を含む。プレイヤーと solver に
渡すのは `Case.public_view()` の `CasePublic` だけ。
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from llm_court.domain.evidence import ResearchReport


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class LearningSource(_Frozen):
    """学習ポイントの出典(捜査結果の証拠品と、その検証済みの引用)。"""

    evidence_id: str
    title: str
    url: str
    quote: str


class LearningPoint(_Frozen):
    id: str
    knowledge: str
    """決め手となる現実の知識。"""
    explanation: str
    sources: list[LearningSource] = Field(min_length=1)
    misconception: str
    """よくある誤解(罠の素)。"""
    outdated: bool = False
    """最近覆った古い知識か。"""
    outdated_belief: str | None = None
    """古い知識の場合、以前の通説。"""


class Person(_Frozen):
    id: str
    name: str
    role: str
    description: str


class TimelineEvent(_Frozen):
    id: str
    order: int
    time: str
    location: str
    person_ids: list[str]
    description: str


class Lie(_Frozen):
    id: str
    witness_id: str
    false_claim: str
    truth_event_id: str
    learning_point_ids: list[str] = Field(min_length=1)


class HiddenTruth(_Frozen):
    summary: str
    timeline: list[TimelineEvent]
    lies: list[Lie]


class CaseEvidence(_Frozen):
    id: str
    name: str
    description: str
    details: list[str]


class TestimonyLine(_Frozen):
    id: str
    text: str
    lie_id: str | None = None
    """この行が嘘なら、その嘘の ID(非公開)。"""


class Testimony(_Frozen):
    id: str
    witness_id: str
    title: str
    lines: list[TestimonyLine] = Field(min_length=1)


class CollapseCondition(_Frozen):
    lie_id: str
    evidence_id: str
    reaction: str
    """正しい証拠品をつきつけられて崩れたときの反応。"""


class WitnessScript(_Frozen):
    witness_id: str
    persona: str
    hidden_facts: list[str]
    lie_ids: list[str]
    collapse_conditions: list[CollapseCondition]


class Trap(_Frozen):
    """罠の選択肢(誤った証拠品と、それを選びたくなる誤解)。"""

    evidence_id: str
    reasoning: str
    """誤解に基づくもっともらしい論法。"""
    learning_point_id: str
    """根拠になっている誤解を持つ学習ポイント。"""
    why_tempting: str


class Contradiction(_Frozen):
    id: str
    testimony_line_id: str
    evidence_id: str
    lie_id: str
    learning_point_ids: list[str] = Field(min_length=1)
    explanation: str
    traps: list[Trap] = []


class CaseQuestion(_Frozen):
    text: str
    options: list[str] = Field(min_length=2)
    answer_index: int


class SolverAccusation(_Frozen):
    testimony_line_id: str
    evidence_id: str
    reasoning: str


class SolverRun(_Frozen):
    """solver の 1 回の解答と採点。"""

    accusations: list[SolverAccusation]
    answer_index: int
    found: list[str]
    """見つけた矛盾の ID。"""
    extra: int
    """正解にない指摘の数。"""
    near_misses: list[str] = []
    """嘘の行は当てたが、別の証拠品をつきつけた矛盾の ID(決め手が一意でない疑い)。"""
    steps: int | None
    """全矛盾を見つけ終えた手数(見つけきれなければ None)。"""
    answer_correct: bool

    @property
    def solved(self) -> bool:
        return self.steps is not None and self.answer_correct


class CheckIssue(_Frozen):
    code: str
    message: str
    step: str
    """作り直す段階(learning_points / hidden_truth / materials / traps)。"""


class CaseValidation(_Frozen):
    validated_at: datetime
    issues: list[CheckIssue]
    solver_runs: list[SolverRun]
    solved: bool
    """全矛盾を見つけ、問いに正答した回があるか。"""
    solve_rate: float = 0.0
    """解けた回の割合(solver の結果は揺れるため、安定性の目安にする)。"""
    unique: bool
    """すべての回で同じ答えになり、余分な指摘がないか。"""
    min_steps: int | None


class CaseGeneration(_Frozen):
    """生成の記録(使ったモデル・プロンプト・計測・作り直しの回数)。"""

    models: dict[str, str]
    prompt_versions: dict[str, str]
    regenerations: dict[str, int]
    llm_calls: int
    input_tokens: int
    output_tokens: int
    llm_time_s: float
    extra: dict[str, Any] = {}


class PublicTestimonyLine(_Frozen):
    id: str
    text: str


class PublicTestimony(_Frozen):
    id: str
    witness_id: str
    title: str
    lines: list[PublicTestimonyLine]


class PublicQuestion(_Frozen):
    text: str
    options: list[str]


class CasePublic(_Frozen):
    """プレイヤーと solver に渡す公開情報。"""

    id: str
    title: str
    overview: str
    question: PublicQuestion
    people: list[Person]
    evidence: list[CaseEvidence]
    testimonies: list[PublicTestimony]


class Case(_Frozen):
    id: str
    theme: str
    title: str
    created_at: datetime
    overview: str
    question: CaseQuestion
    people: list[Person]
    evidence: list[CaseEvidence]
    testimonies: list[Testimony]
    learning_points: list[LearningPoint]
    hidden_truth: HiddenTruth
    witness_scripts: list[WitnessScript]
    contradictions: list[Contradiction]
    research: ResearchReport
    generation: CaseGeneration | None = None
    validation: CaseValidation | None = None

    def public_view(self) -> CasePublic:
        return CasePublic(
            id=self.id,
            title=self.title,
            overview=self.overview,
            question=PublicQuestion(text=self.question.text, options=self.question.options),
            people=self.people,
            evidence=self.evidence,
            testimonies=[
                PublicTestimony(
                    id=t.id,
                    witness_id=t.witness_id,
                    title=t.title,
                    lines=[PublicTestimonyLine(id=line.id, text=line.text) for line in t.lines],
                )
                for t in self.testimonies
            ],
        )

    @property
    def testimony_lines(self) -> dict[str, TestimonyLine]:
        return {line.id: line for t in self.testimonies for line in t.lines}
