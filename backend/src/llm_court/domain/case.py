"""裁判型の事件(架空の事件・真相・証拠品・証言・台本・矛盾・学習ポイント)。

法廷に立つのは裁判官・検察官(プレイヤー)・被告の 3 人で、証言するのは被告だけ(ADR 0017)。
`Case` は非公開の情報(真相・台本・矛盾・正解・学習ポイント)を含む。プレイヤーと solver に
渡すのは `Case.public_view()` の `CasePublic` だけ。
"""

from collections.abc import Collection
from datetime import datetime
from typing import Any, Literal

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


class CaseVerdict(_Frozen):
    """全矛盾を解いたあとの判決(ADR 0020)。裁判官が刑罰を言い渡し、被告が反応する。"""

    sentence: str
    """刑罰(例: 3日間おやつ抜き)。"""
    defendant_reaction: str
    """判決を聞いた被告の台詞。"""


class EvidenceUnlock(_Frozen):
    """尋問の中で手に入る証拠品(ADR 0019)。

    決まった行動を取るまで、法廷記録に出さず、つきつけられない。

    例: ある証言の行を「ゆさぶる」と、被告が口をすべらせて新しい証拠品になる。
    """

    evidence_id: str
    kind: Literal["probe", "present"] = "probe"
    """手に入れる行動の種類(ゆさぶる / つきつける)。"""
    line_id: str
    """その行動の対象の証言の行。"""
    presented_evidence_id: str | None = None
    """つきつけるで手に入れる場合の、つきつける証拠品。"""

    def triggered_by(self, tried: Collection[tuple[str, str, str | None]]) -> bool:
        """選択済みの行動 (kind, line_id, evidence_id) に、手に入れる行動が含まれるか。"""
        evidence = self.presented_evidence_id if self.kind == "present" else None
        return (self.kind, self.line_id, evidence) in tried


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
    """解答率が `min_solve_rate` 以上か(1 回だけ偶然解けた事件を合格にしない)。"""
    solve_rate: float = 0.0
    """全矛盾を見つけ、問いに正答した回 ÷ 試行回数(答えを返せなかった回も分母に含む)。"""
    detect_rate: float = 0.0
    """全矛盾を見つけた回 ÷ 試行回数(問いの正誤を問わない)。"""
    answer_rate: float = 0.0
    """問いに正答した回 ÷ 試行回数。"""
    attempted_runs: int = 0
    min_solve_rate: float = 0.0
    """判定に使った解答率の下限。"""
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
    defendant_id: str | None = None
    """被告(証言する人物)。None は被告を持たない旧形式の事件。"""
    prosecutor_id: str | None = None
    """検察官(プレイヤー)を演じる人物。None なら名前のない検察官。"""
    prosecutor_speech: Literal["plain", "cat"] = "plain"
    """検察官の台詞(定型文)の口調。cat は猫言葉(語尾に「にゃ」)。"""


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
    prosecutor_id: str | None = None
    """検察官(プレイヤー)を演じる人物(公開。名札に名前を出す)。None なら名前のない検察官。"""
    prosecutor_speech: Literal["plain", "cat"] = "plain"
    """検察官の台詞(画面の定型文)の口調(公開)。cat は猫言葉。"""
    evidence_unlocks: list[EvidenceUnlock] = []
    verdict: CaseVerdict | None = None
    """判決の刑罰と被告の反応(非公開。閉廷後の解説で出す)。None なら画面の定型文を使う。"""
    """尋問の中で手に入る証拠品(非公開。手に入るまで法廷記録に出さない)。"""
    defendant_id: str | None = None
    """被告。検察官の尋問に答え、嘘をつくのは被告だけ(ADR 0017)。None は旧形式の事件
    (複数の証人が証言する。読み込めるが、整合性チェックには通らない)。"""
    generation: CaseGeneration | None = None
    validation: CaseValidation | None = None

    @property
    def locked_evidence_ids(self) -> set[str]:
        """尋問の中で手に入る(初めは持っていない)証拠品。"""
        return {u.evidence_id for u in self.evidence_unlocks}

    def available_evidence_ids(self, tried: Collection[tuple[str, str, str | None]]) -> set[str]:
        """選択済みの行動 (kind, line_id, evidence_id) のあとで、手元にある証拠品。"""
        unlocked = {u.evidence_id for u in self.evidence_unlocks if u.triggered_by(tried)}
        locked = self.locked_evidence_ids - unlocked
        return {e.id for e in self.evidence if e.id not in locked}

    def public_view(self, available: Collection[str] | None = None) -> CasePublic:
        """公開情報。証拠品は手元にあるものだけ。

        `available` を省くと、初めから持っているものだけにする。
        """
        shown = set(available) if available is not None else self.available_evidence_ids(())
        return CasePublic(
            id=self.id,
            title=self.title,
            overview=self.overview,
            question=PublicQuestion(text=self.question.text, options=self.question.options),
            people=self.people,
            evidence=[e for e in self.evidence if e.id in shown],
            testimonies=[
                PublicTestimony(
                    id=t.id,
                    witness_id=t.witness_id,
                    title=t.title,
                    lines=[PublicTestimonyLine(id=line.id, text=line.text) for line in t.lines],
                )
                for t in self.testimonies
            ],
            defendant_id=self.defendant_id,
            prosecutor_id=self.prosecutor_id,
            prosecutor_speech=self.prosecutor_speech,
        )

    @property
    def testimony_lines(self) -> dict[str, TestimonyLine]:
        return {line.id: line for t in self.testimonies for line in t.lines}
