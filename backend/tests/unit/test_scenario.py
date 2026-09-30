import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest

from llm_court.config import ScenarioSettings
from llm_court.domain import Case, ResearchReport
from llm_court.llm import ChatRequest, InMemoryRecorder, LLMClient, PromptLoader
from llm_court.modes import TRIAL_MODE
from llm_court.scenario.checks import check_case, earliest_step
from llm_court.scenario.drafts import (
    DraftError,
    HiddenTruthOutput,
    LearningPointsOutput,
    to_hidden_truth,
    to_learning_points,
)
from llm_court.scenario.generator import CaseGenerationError, CaseGenerator
from llm_court.scenario.solver import SolverOutput, score, summarize_runs
from llm_court.scenario.store import CaseNotFoundError, CaseStore
from tests.case_fakes import (
    HIDDEN_TRUTH,
    LEAK,
    LEARNING_POINTS,
    MATERIALS,
    SOLVED,
    UNSOLVED,
    CaseResponder,
    text,
)
from tests.fakes import FakeChatBackend, FakeResponse
from tests.unit.test_llm_client import make_config


def make_generator(
    prompts: PromptLoader,
    responder: CaseResponder,
    *,
    max_regenerations: int = 2,
    draft_retries: int = 1,
    solver_runs: int = 2,
    check_overview_leaks: bool = True,
    research: Any = None,
) -> CaseGenerator:
    fake = FakeChatBackend(responder=responder)
    recorder = InMemoryRecorder()
    llm = LLMClient(
        make_config(),
        prompts=prompts,
        structured_max_retries=0,
        backend_factory=lambda _p: fake,
        recorder=recorder,
    )
    return CaseGenerator(
        llm=llm,
        recorder=recorder,
        prompts=prompts,
        mode=TRIAL_MODE,
        settings=ScenarioSettings(
            max_regenerations=max_regenerations,
            draft_retries=draft_retries,
            solver_runs=solver_runs,
            check_overview_leaks=check_overview_leaks,
        ),
        research=research,
    )


async def generate(
    prompts: PromptLoader, report: ResearchReport, responder: CaseResponder, **kwargs: Any
) -> Case:
    return await make_generator(prompts, responder, **kwargs).generate("給付", evidence=report)


# --- 下書きの変換 ---


def test_learning_points_link_verified_facts(research_report: ResearchReport) -> None:
    points = to_learning_points(
        LearningPointsOutput.model_validate(LEARNING_POINTS), research_report.evidence, limit=3
    )
    assert [p.id for p in points] == ["LP-01", "LP-02"]  # 出典が確認できない 3 つ目は除く
    assert points[0].sources[0].quote.startswith("雇用には大きな効果は見られなかった")
    assert points[1].sources[0].evidence_id == "EV-02"  # 表記ゆれ(ev-2)を正規化
    assert points[1].outdated and points[1].outdated_belief


def test_learning_points_require_two(research_report: ResearchReport) -> None:
    data = {"points": LEARNING_POINTS["points"][2:]}
    with pytest.raises(DraftError, match="2 つ未満"):
        to_learning_points(LearningPointsOutput.model_validate(data), research_report.evidence, 3)


def test_hidden_truth_reports_unknown_keys(research_report: ResearchReport) -> None:
    points = to_learning_points(
        LearningPointsOutput.model_validate(LEARNING_POINTS), research_report.evidence, 3
    )
    data = copy.deepcopy(HIDDEN_TRUTH)
    data["defendant_key"] = "p9"
    data["timeline"][0]["person_keys"] = ["p8"]
    with pytest.raises(DraftError) as e:
        to_hidden_truth(HiddenTruthOutput.model_validate(data), points)
    assert any("p9" in p for p in e.value.problems)
    assert any("p8" in p for p in e.value.problems)


# --- 生成パイプライン ---


async def test_generate_solvable_case(
    prompts: PromptLoader, research_report: ResearchReport
) -> None:
    responder = CaseResponder()
    case = await generate(prompts, research_report, responder)

    assert [p.id for p in case.people] == ["P-01", "P-02", "P-03"]
    assert [lie.id for lie in case.hidden_truth.lies] == ["L-01", "L-02"]
    # 被告だけが嘘をつき、証言する(ADR 0017)
    assert case.defendant_id == "P-02"
    assert {lie.witness_id for lie in case.hidden_truth.lies} == {"P-02"}
    assert {t.witness_id for t in case.testimonies} == {"P-02"}
    assert [e.id for e in case.evidence] == ["CE-01", "CE-02", "CE-03", "CE-04"]
    x1, x2 = case.contradictions
    assert (x1.testimony_line_id, x1.evidence_id, x1.lie_id) == ("TS-01-2", "CE-01", "L-01")
    assert [t.evidence_id for t in x1.traps] == ["CE-03"]  # 正解と同じ証拠品の罠は捨てる
    assert [t.evidence_id for t in x2.traps] == ["CE-04"]
    [script] = case.witness_scripts
    assert script.witness_id == "P-02"
    assert script.lie_ids == ["L-01", "L-02"]
    assert [c.evidence_id for c in script.collapse_conditions] == ["CE-01", "CE-02"]

    assert check_case(case, TRIAL_MODE) == []
    v = case.validation
    assert v is not None
    assert v.solved and v.unique and v.min_steps == 2
    assert len(v.solver_runs) == 2
    g = case.generation
    assert g is not None
    assert g.llm_calls == 7  # 4 段階 + 漏れの検査 + solver 2 回
    assert "scenario_writer/materials" in g.prompt_versions
    assert g.models["solver"]


async def test_public_view_hides_secrets(
    prompts: PromptLoader, research_report: ResearchReport
) -> None:
    case = await generate(prompts, research_report, CaseResponder())
    public = case.public_view().model_dump_json()
    for secret in ("lie_id", "L-01", "LP-01", "answer_index", "hidden_truth", "misconception"):
        assert secret not in public
    assert "実験では就業率が半分に落ちました" in public
    assert "被告が報告書で偽った内容は何か" in public
    assert case.public_view().defendant_id == "P-02"


async def test_solver_sees_only_public_info(
    prompts: PromptLoader, research_report: ResearchReport
) -> None:
    responder = CaseResponder()
    await generate(prompts, research_report, responder)
    solver_prompt = responder.requests["SolverOutput"][0].messages[-1].content
    assert "TS-01-2" in solver_prompt and "CE-01" in solver_prompt
    assert "L-01" not in solver_prompt and "LP-01" not in solver_prompt
    assert HIDDEN_TRUTH["summary"] not in solver_prompt


async def test_draft_retry_with_feedback(
    prompts: PromptLoader, research_report: ResearchReport
) -> None:
    broken = copy.deepcopy(HIDDEN_TRUTH)
    broken["lies"][0]["truth_event_key"] = "t99"

    def hidden(n: int, _r: ChatRequest) -> FakeResponse:
        return text(broken if n == 0 else HIDDEN_TRUTH)

    responder = CaseResponder({"HiddenTruthOutput": hidden})
    case = await generate(prompts, research_report, responder)
    second = responder.requests["HiddenTruthOutput"][1].messages[0].content
    assert "前回の出力には次の問題がありました" in second and "t99" in second
    assert case.generation is not None
    assert case.generation.regenerations["hidden_truth"] == 1


async def test_regenerates_materials_when_unsolved(
    prompts: PromptLoader, research_report: ResearchReport
) -> None:
    def solver(n: int, _r: ChatRequest) -> FakeResponse:
        return text(UNSOLVED if n < 2 else SOLVED)  # 1 巡目の 2 回は解けない

    responder = CaseResponder({"SolverOutput": solver})
    case = await generate(prompts, research_report, responder)
    assert case.validation is not None and case.validation.solved
    assert responder.calls["MaterialsOutput"] == 2
    assert responder.calls["HiddenTruthOutput"] == 1
    feedback = responder.requests["MaterialsOutput"][1].messages[0].content
    assert "嘘に気づかれませんでした" in feedback
    assert "最後の問いに 2 回中 2 回誤答しました。問いは評価や程度" in feedback
    assert "嘘でない証言「結果は 4 月 2 日に届きました」が CE-04 と矛盾して見えました" in feedback
    assert case.generation is not None
    assert case.generation.regenerations["round:materials"] == 1


async def test_check_failure_regenerates_earliest_step(
    prompts: PromptLoader, research_report: ResearchReport
) -> None:
    # 公開する概要に非公開の ID が入る → 規則のチェックで資料を作り直す
    leaking = copy.deepcopy(MATERIALS)
    leaking["overview"] = "L-01 の嘘を暴く事件"

    def materials(n: int, _r: ChatRequest) -> FakeResponse:
        return text(leaking if n == 0 else MATERIALS)

    responder = CaseResponder({"MaterialsOutput": materials})
    case = await generate(prompts, research_report, responder)
    assert case.validation is not None and case.validation.solved
    feedback = responder.requests["MaterialsOutput"][1].messages[0].content
    assert "公開する文に非公開の ID があります" in feedback
    assert responder.calls["SolverOutput"] == 2  # チェックに失敗した回は solver にかけない


async def test_contradiction_inherits_lie_learning_points(
    prompts: PromptLoader, research_report: ResearchReport
) -> None:
    # 資料の段階で学習ポイントを書き漏れても、嘘に設定した学習ポイントを引き継ぐ
    missing = copy.deepcopy(MATERIALS)
    missing["contradictions"][1]["learning_point_ids"] = ["LP-01"]
    responder = CaseResponder({"MaterialsOutput": lambda _n, _r: text(missing)})
    case = await generate(prompts, research_report, responder)
    assert case.contradictions[1].learning_point_ids == ["LP-02", "LP-01"]
    assert check_case(case, TRIAL_MODE) == []


async def test_unused_learning_point_is_retried_in_hidden_truth(
    prompts: PromptLoader, research_report: ResearchReport
) -> None:
    only_lp1 = copy.deepcopy(HIDDEN_TRUTH)
    only_lp1["lies"][1]["learning_point_ids"] = ["LP-01"]

    def hidden(n: int, _r: ChatRequest) -> FakeResponse:
        return text(only_lp1 if n == 0 else HIDDEN_TRUTH)

    responder = CaseResponder({"HiddenTruthOutput": hidden})
    await generate(prompts, research_report, responder)
    feedback = responder.requests["HiddenTruthOutput"][1].messages[0].content
    assert "学習ポイント LP-02 を見抜くのに使う嘘がありません" in feedback


async def test_duplicate_contradiction_is_retried_in_draft(
    prompts: PromptLoader, research_report: ResearchReport
) -> None:
    duplicated = copy.deepcopy(MATERIALS)
    duplicated["contradictions"].append(dict(duplicated["contradictions"][0], evidence_key="e3"))

    def materials(n: int, _r: ChatRequest) -> FakeResponse:
        return text(duplicated if n == 0 else MATERIALS)

    responder = CaseResponder({"MaterialsOutput": materials})
    case = await generate(prompts, research_report, responder)
    assert case.generation is not None
    assert case.generation.regenerations["materials"] == 1  # 全体をやり直さず、この段階だけ
    assert "round:materials" not in case.generation.regenerations
    feedback = responder.requests["MaterialsOutput"][1].messages[0].content
    assert "嘘 L-01 の矛盾が 2 件あります" in feedback


async def test_gives_up_after_max_regenerations(
    prompts: PromptLoader, research_report: ResearchReport
) -> None:
    responder = CaseResponder({"SolverOutput": lambda _n, _r: text(UNSOLVED)})
    case = await generate(prompts, research_report, responder, max_regenerations=1)
    assert case.validation is not None and not case.validation.solved
    assert responder.calls["MaterialsOutput"] == 2


async def test_draft_error_exhausts(prompts: PromptLoader, research_report: ResearchReport) -> None:
    bad = {"points": LEARNING_POINTS["points"][2:]}
    responder = CaseResponder({"LearningPointsOutput": lambda _n, _r: text(bad)})
    with pytest.raises(CaseGenerationError, match="learning_points"):
        await generate(prompts, research_report, responder, draft_retries=1)


async def test_research_is_used_without_evidence(
    prompts: PromptLoader, research_report: ResearchReport
) -> None:
    topics: list[str] = []

    async def research(topic: str, _progress: Callable[[str], None]) -> ResearchReport:
        topics.append(topic)
        return research_report

    generator = make_generator(prompts, CaseResponder(), research=research)
    case = await generator.generate("給付")
    assert topics == ["給付"]
    assert case.research == research_report


# --- 整合性チェック ---


async def valid_case(prompts: PromptLoader, report: ResearchReport) -> Case:
    return await generate(prompts, report, CaseResponder())


Patch = dict[str, Any] | str


def apply_patch(data: dict[str, Any], path: str, patch: Patch) -> None:
    """`path`(a.b.0 形式)の要素を更新する。`patch` が "pop" なら最後の要素を取り除く。"""
    target: Any = data
    for key in [k for k in path.split(".") if k]:
        if isinstance(target, list):
            target = cast(list[Any], target)[int(key)]
        else:
            target = cast(dict[str, Any], target)[key]
    if patch == "pop":
        cast(list[Any], target).pop()
    else:
        cast(dict[str, Any], target).update(cast(dict[str, Any], patch))


@pytest.mark.parametrize(
    ("path", "patch", "code", "step"),
    [
        ("hidden_truth.timeline.1", {"order": 1}, "timeline_order", "hidden_truth"),
        (
            "hidden_truth.timeline.1",
            {"time": "4月1日", "location": "別の場所", "person_ids": ["P-01"]},
            "timeline_conflict",
            "hidden_truth",
        ),
        ("hidden_truth.lies", "pop", "lie_count", "hidden_truth"),
        ("contradictions", "pop", "lie_contradiction", "materials"),
        ("contradictions.0", {"testimony_line_id": "TS-01-1"}, "line_lie_mismatch", "materials"),
        (
            "contradictions.1",
            {"learning_point_ids": ["LP-01"]},
            "unused_learning_point",
            "materials",
        ),
        ("witness_scripts.0", {"collapse_conditions": []}, "missing_collapse", "materials"),
        ("", {"overview": "L-01 の嘘を暴く"}, "public_leak", "materials"),
        ("question", {"answer_index": 9}, "question_answer", "materials"),
        ("contradictions.0", {"traps": []}, "missing_trap", "traps"),
        ("contradictions.0.traps.0", {"evidence_id": "CE-01"}, "trap_is_answer", "traps"),
    ],
)
async def test_checks_detect_problems(
    prompts: PromptLoader,
    research_report: ResearchReport,
    path: str,
    patch: Patch,
    code: str,
    step: str,
) -> None:
    data = json.loads((await valid_case(prompts, research_report)).model_dump_json())
    apply_patch(data, path, patch)
    issues = check_case(Case.model_validate(data), TRIAL_MODE)
    assert code in {i.code for i in issues}
    assert next(i.step for i in issues if i.code == code) == step


def test_earliest_step() -> None:
    from llm_court.domain import CheckIssue

    issues = [
        CheckIssue(code="a", message="", step="traps"),
        CheckIssue(code="b", message="", step="hidden_truth"),
    ]
    assert earliest_step(issues) == "hidden_truth"
    assert earliest_step([]) is None


# --- solver の採点 ---


async def test_score(prompts: PromptLoader, research_report: ResearchReport) -> None:
    case = await valid_case(prompts, research_report)
    partial = SolverOutput.model_validate(
        {
            "accusations": [
                {"testimony_line_id": "TS-01-1", "evidence_id": "CE-04", "reasoning": "x"},
                {"testimony_line_id": "TS-01-2", "evidence_id": "CE-01", "reasoning": "x"},
                {"testimony_line_id": "TS-01-2", "evidence_id": "CE-01", "reasoning": "重複"},
                {"testimony_line_id": "TS-02-2", "evidence_id": "CE-02", "reasoning": "x"},
            ],
            "answer_index": 1,
        }
    )
    run = score(case, partial)
    assert run.found == ["X-01", "X-02"]
    assert run.extra == 1
    assert run.steps == 4 and run.solved

    unsolved = score(case, SolverOutput.model_validate(UNSOLVED))
    assert unsolved.found == [] and unsolved.steps is None and not unsolved.solved

    validation = summarize_runs([run, score(case, SolverOutput.model_validate(SOLVED))], [])
    assert validation.solved and not validation.unique  # 余分な指摘がある
    assert validation.solve_rate == 1.0
    # 1 回だけ偶然解けた事件は、基準の解答率に届かなければ合格にしない
    mixed = summarize_runs([run, unsolved], [], min_solve_rate=0.6)
    assert mixed.solve_rate == 0.5 and not mixed.solved
    assert summarize_runs([run, unsolved], [], min_solve_rate=0.5).solved
    # 答えを返せなかった回も分母に含める
    failed_one = summarize_runs([run, run], [], attempted=3, min_solve_rate=0.6)
    assert failed_one.attempted_runs == 3 and round(failed_one.solve_rate, 2) == 0.67
    assert failed_one.solved
    assert failed_one.detect_rate == failed_one.answer_rate == failed_one.solve_rate
    detected_but_wrong = run.model_copy(update={"answer_correct": False})
    split = summarize_runs([detected_but_wrong, run], [], min_solve_rate=0.6)
    assert (split.detect_rate, split.answer_rate, split.solve_rate) == (1.0, 0.5, 0.5)
    assert validation.min_steps == 2
    assert not summarize_runs([], []).solved


# --- 保存 ---


async def test_store(
    tmp_path: Path, prompts: PromptLoader, research_report: ResearchReport
) -> None:
    store = CaseStore(tmp_path / "cases")
    assert store.list() == []
    case = await valid_case(prompts, research_report)
    path = store.save(case)
    assert path.name == f"{case.id}.json"
    assert store.load(case.id) == case
    assert [c.id for c in store.list()] == [case.id]
    with pytest.raises(CaseNotFoundError):
        store.load("../etc")
    with pytest.raises(CaseNotFoundError):
        store.load("nope")


async def test_near_miss_is_reported(
    prompts: PromptLoader, research_report: ResearchReport
) -> None:
    # 嘘の行は当てたが、別の証拠品をつきつけた(決め手が一意でない疑い)
    near: dict[str, Any] = {
        "accusations": [
            {"testimony_line_id": "TS-01-2", "evidence_id": "CE-03", "reasoning": "議事録と違う"},
            {"testimony_line_id": "TS-02-2", "evidence_id": "CE-02", "reasoning": "桁が合わない"},
        ],
        "answer_index": 1,
    }

    def solver(n: int, _r: ChatRequest) -> FakeResponse:
        return text(near if n < 2 else SOLVED)

    responder = CaseResponder({"SolverOutput": solver})
    case = await generate(prompts, research_report, responder)
    first = score(case, SolverOutput.model_validate(near))
    assert first.found == ["X-02"] and first.near_misses == ["X-01"] and not first.solved
    feedback = responder.requests["MaterialsOutput"][1].messages[0].content
    assert "正解の CE-01 ではなく CE-03 で気づかれました" in feedback


def test_replace_keys() -> None:
    from llm_court.scenario.drafts import replace_keys

    names = {"p1": "朝霧", "p2": "白波", "e1": "CE-01"}
    assert replace_keys("p2 は e1 を見て p1 に伝えた(p10 と ep1 はそのまま)", names) == (
        "白波 は CE-01 を見て 朝霧 に伝えた(p10 と ep1 はそのまま)"
    )
    assert replace_keys("変更なし", {}) == "変更なし"


async def test_validation_uses_solve_rate(
    prompts: PromptLoader, research_report: ResearchReport
) -> None:
    # 3 回中 1 回しか解けない事件は、基準 0.6 に届かないので作り直す
    def solver(n: int, _r: ChatRequest) -> FakeResponse:
        first_round = n < 3
        return text(SOLVED if (not first_round or n == 0) else UNSOLVED)

    responder = CaseResponder({"SolverOutput": solver})
    case = await make_generator(prompts, responder, solver_runs=3).generate(
        "給付", evidence=research_report
    )
    assert responder.calls["MaterialsOutput"] == 2
    assert case.validation is not None
    assert case.validation.solved and case.validation.solve_rate == 1.0
    assert case.validation.attempted_runs == 3


# --- 公開する概要の漏れ ---


async def test_overview_leak_regenerates_materials(
    prompts: PromptLoader, research_report: ResearchReport
) -> None:
    def leaks(n: int, _r: ChatRequest) -> FakeResponse:
        return text(LEAK if n == 0 else {"leaks": []})

    responder = CaseResponder({"LeakCheckOutput": leaks})
    case = await generate(prompts, research_report, responder)
    assert case.validation is not None and case.validation.solved
    assert responder.calls["MaterialsOutput"] == 2
    feedback = responder.requests["MaterialsOutput"][1].messages[0].content
    # 概要にある引用だけを採用する(概要にない引用・存在しない嘘は捨てる)
    assert "「報告書に不審な点があり」が、嘘 L-01 の答えを明かしています" in feedback
    assert "概要にない引用" not in feedback and "L-09" not in feedback
    # 漏れの検査は判定に非公開の嘘と真相を使い、solver は漏れがなくなってから呼ぶ
    leak_prompt = responder.requests["LeakCheckOutput"][0].messages[-1].content
    assert "L-01" in leak_prompt and "実験結果が届く" in leak_prompt
    assert responder.calls["SolverOutput"] == 2


async def test_leak_check_can_be_disabled(
    prompts: PromptLoader, research_report: ResearchReport
) -> None:
    responder = CaseResponder({"LeakCheckOutput": lambda _n, _r: text(LEAK)})
    generator = make_generator(prompts, responder, check_overview_leaks=False)
    case = await generator.generate("給付", evidence=research_report)
    assert case.validation is not None and case.validation.solved
    assert "LeakCheckOutput" not in responder.calls


async def test_validate_reports_leak(
    prompts: PromptLoader, research_report: ResearchReport
) -> None:
    case = await generate(prompts, research_report, CaseResponder())
    responder = CaseResponder({"LeakCheckOutput": lambda _n, _r: text(LEAK)})
    validated = await make_generator(prompts, responder).validate(case)
    assert validated.validation is not None
    assert [i.code for i in validated.validation.issues] == ["overview_leak"]


async def test_check_case_requires_the_defendant_to_testify(
    prompts: PromptLoader, research_report: ResearchReport
) -> None:
    """証言し嘘をつくのは被告だけ。被告のない旧形式の事件はチェックに通らない。"""
    case = await generate(prompts, research_report, CaseResponder())
    assert check_case(case, TRIAL_MODE) == []

    def codes(c: Case) -> set[str]:
        return {i.code for i in check_case(c, TRIAL_MODE)}

    assert "missing_defendant" in codes(case.model_copy(update={"defendant_id": None}))
    other = case.model_copy(update={"defendant_id": "P-03"})
    assert {"lie_not_defendant", "testimony_not_defendant", "script_not_defendant"} <= codes(other)
