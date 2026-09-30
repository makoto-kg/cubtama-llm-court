from pathlib import Path

import pytest
from typer.testing import CliRunner

from llm_court.cli.main import app
from llm_court.modes import TRIAL_MODE
from llm_court.offline.models import OfflineIndex, OfflinePack
from llm_court.offline.scripted import (
    ScriptedScenarioError,
    build_scripted_pack,
    load_scenario,
    validate_scenario,
)
from llm_court.offline.simulate import build_index, enumerate_actions

BACKEND_ROOT = Path(__file__).resolve().parents[2]
TUTORIAL = BACKEND_ROOT / "scenarios" / "tutorial-churu.yaml"
BUNDLED = BACKEND_ROOT.parent / "frontend" / "public" / "offline"
runner = CliRunner()


def test_tutorial_scenario_is_valid() -> None:
    scenario = load_scenario(TUTORIAL)
    assert validate_scenario(scenario, TRIAL_MODE) == []
    pack = build_scripted_pack(scenario, TRIAL_MODE)
    assert pack.meta.source == "scripted" and pack.meta.tutorial
    assert {r.key for r in pack.responses} == {a.key for a in enumerate_actions(scenario.case)}
    collapsing = [r.key for r in pack.responses if r.should_collapse]
    assert collapsing == [
        "present:TS-01-2:CE-04",
        "present:TS-01-3:CE-01",
        "present:TS-02-1:CE-05",
        "present:TS-02-2:CE-06",
    ]
    assert pack.explanation.items[0].traps[0].evidence_name == "飼い主さんのメモ"


def test_bundled_tutorial_pack_is_up_to_date() -> None:
    """同梱のパックは台本から作り直したものと一致する(台本だけ直して作り直し忘れるのを防ぐ)。"""
    built = build_scripted_pack(load_scenario(TUTORIAL), TRIAL_MODE)
    bundled = OfflinePack.model_validate_json(
        (BUNDLED / "cases" / f"{built.case.id}.json").read_text(encoding="utf-8")
    )
    assert bundled == built


def test_missing_and_extra_responses_are_rejected() -> None:
    scenario = load_scenario(TUTORIAL)
    responses = dict(scenario.responses)
    del responses["probe:TS-01-1"]
    responses["probe:TS-99-1"] = "?"
    broken = scenario.model_copy(update={"responses": responses})
    problems = validate_scenario(broken, TRIAL_MODE)
    assert "応答がありません: probe:TS-01-1" in problems
    assert "使われない応答があります: probe:TS-99-1" in problems
    with pytest.raises(ScriptedScenarioError):
        build_scripted_pack(broken, TRIAL_MODE)


def test_inconsistent_case_is_rejected() -> None:
    scenario = load_scenario(TUTORIAL)
    case = scenario.case.model_copy(update={"witness_scripts": []})
    problems = validate_scenario(scenario.model_copy(update={"case": case}), TRIAL_MODE)
    assert any(p.startswith("missing_collapse") for p in problems)


def test_index_lists_tutorials_first() -> None:
    tutorial = build_scripted_pack(load_scenario(TUTORIAL), TRIAL_MODE)
    older = tutorial.meta.generated_at.replace(year=2000)
    other = tutorial.model_copy(
        update={
            "case": tutorial.case.model_copy(update={"id": "other"}),
            # 生成が古くても、チュートリアルが先
            "meta": tutorial.meta.model_copy(update={"tutorial": False, "generated_at": older}),
        }
    )
    index = build_index([other, tutorial])
    assert [(c.id, c.tutorial) for c in index.cases] == [("tutorial-churu", True), ("other", False)]


def test_cli_scripted(tmp_path: Path) -> None:
    result = runner.invoke(app, ["offline", "scripted", str(TUTORIAL), "--out", str(tmp_path)])
    assert result.exit_code == 0, result.output
    index = OfflineIndex.model_validate_json((tmp_path / "index.json").read_text("utf-8"))
    assert [c.id for c in index.cases] == ["tutorial-churu"]
    assert (tmp_path / "cases" / "tutorial-churu.json").exists()

    bad = tmp_path / "bad.yaml"
    bad.write_text("case: {}\nresponses: {}\n", encoding="utf-8")
    assert (
        runner.invoke(app, ["offline", "scripted", str(bad), "--out", str(tmp_path)]).exit_code == 1
    )
