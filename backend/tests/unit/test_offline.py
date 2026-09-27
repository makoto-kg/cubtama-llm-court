from pathlib import Path

import pytest
from typer.testing import CliRunner

from llm_court.api import create_app
from llm_court.cli import main as cli_main
from llm_court.cli.main import app
from llm_court.domain import Case, ResearchReport
from llm_court.engine.recorder import BufferedRecorder
from llm_court.llm import LLMClient, PromptLoader
from llm_court.llm.client import BackendFactory
from llm_court.modes import TRIAL_MODE
from llm_court.offline.models import OfflineIndex, OfflinePack, present_key, probe_key
from llm_court.offline.simulate import OfflineSimulator, enumerate_actions
from llm_court.scenario.store import CaseStore
from tests.fakes import FakeChatBackend
from tests.trial_fakes import COLLAPSE_TEXT, EVADE_TEXT, TrialResponder, make_case
from tests.unit.test_llm_client import make_config

BACKEND_ROOT = Path(__file__).resolve().parents[2]
runner = CliRunner()


@pytest.fixture
async def case(prompts: PromptLoader, research_report: ResearchReport) -> Case:
    return await make_case(prompts, research_report)


def make_simulator(
    prompts: PromptLoader, responder: TrialResponder, *, retries: int = 2, check: bool = True
) -> OfflineSimulator:
    fake = FakeChatBackend(responder=responder)
    llm = LLMClient(
        make_config(),
        prompts=prompts,
        structured_max_retries=0,
        backend_factory=lambda _p: fake,
        recorder=BufferedRecorder(),
    )
    return OfflineSimulator(
        llm=llm, prompts=prompts, mode=TRIAL_MODE, retries=retries, check_deviations=check
    )


def test_enumerate_actions_covers_all_options(case: Case) -> None:
    actions = enumerate_actions(case)
    keys = [a.key for a in actions]
    assert len(keys) == len(set(keys))
    # 矛盾のある証言(2 件)× 行(2 行)×(ゆさぶる 1 + 証拠品 4)
    assert len(keys) == 2 * 2 * (1 + len(case.evidence))
    assert probe_key("TS-01-1") in keys
    assert present_key("TS-02-2", "CE-02") in keys
    correct = {a.key: a.option.contradiction_id for a in actions if a.option.contradiction_id}
    assert correct == {
        present_key("TS-01-2", "CE-01"): "X-01",
        present_key("TS-02-2", "CE-02"): "X-02",
    }


async def test_build_pack(prompts: PromptLoader, case: Case) -> None:
    responder = TrialResponder()
    pack = await make_simulator(prompts, responder).build(case)
    by_key = {r.key: r for r in pack.responses}
    assert len(by_key) == len(enumerate_actions(case))
    collapse = by_key[present_key("TS-01-2", "CE-01")]
    assert collapse.should_collapse and collapse.text == COLLAPSE_TEXT
    assert by_key[probe_key("TS-01-1")].text == EVADE_TEXT
    assert all(
        r.attempts == 1 and r.check is not None and not r.check.deviations for r in pack.responses
    )
    assert all(r.call is not None and r.call.role == "witness" for r in pack.responses)
    # 履歴なしで生成する
    assert all("これまでのやりとり" not in str(r.messages) for r in responder.requests["text"])

    assert pack.meta.responses == len(pack.responses) and pack.meta.deviations == 0
    assert pack.meta.models == {"witness": "big", "judge": "big"}
    assert pack.meta.prompt_versions["witness/respond"]
    assert pack.answers.answer_index == case.question.answer_index
    assert [c.id for c in pack.answers.contradictions] == ["X-01", "X-02"]
    assert pack.answers.contradictions[0].traps[0].evidence_id == "CE-03"
    assert pack.explanation.items and pack.mode.penalty_gauge == TRIAL_MODE.penalty_gauge
    # 公開ビューには非公開の情報がない
    assert "hidden_truth" not in pack.case.model_dump()
    # JSON で往復できる
    assert OfflinePack.model_validate_json(pack.model_dump_json()) == pack


async def test_deviating_responses_are_regenerated(prompts: PromptLoader, case: Case) -> None:
    responder = TrialResponder(confess_always=True)
    pack = await make_simulator(prompts, responder, retries=2).build(case)
    probe = next(r for r in pack.responses if r.key == probe_key("TS-01-1"))
    assert probe.attempts == 3  # 逸脱が消えないので上限まで作り直す
    assert probe.check is not None and probe.check.deviations == ["premature_confession"]
    correct = next(r for r in pack.responses if r.should_collapse)
    assert correct.attempts == 1  # 崩れるべき場面の自白は逸脱ではない
    assert pack.meta.deviations == len(pack.responses) - len(case.contradictions)


async def test_without_check(prompts: PromptLoader, case: Case) -> None:
    responder = TrialResponder(confess_always=True)
    pack = await make_simulator(prompts, responder, check=False).build(case)
    assert all(r.check is None and r.attempts == 1 for r in pack.responses)
    assert "DeviationOutput" not in responder.requests
    assert "judge" not in pack.meta.models


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, case: Case) -> Path:
    fake = FakeChatBackend(responder=TrialResponder())
    factory: BackendFactory = lambda _p: fake  # noqa: E731
    monkeypatch.setattr(cli_main, "backend_factory", factory)
    monkeypatch.setenv("COLUMNS", "200")
    monkeypatch.setenv("LLM_COURT_MODELS_CONFIG_PATH", str(BACKEND_ROOT / "config/models.yaml"))
    monkeypatch.setenv("LLM_COURT_PROMPTS_DIR", str(BACKEND_ROOT / "prompts"))
    monkeypatch.setenv("LLM_COURT_SCENARIO__CASE_DIR", str(tmp_path / "cases"))
    monkeypatch.setenv("LLM_COURT_OFFLINE_OUTPUT_DIR", str(tmp_path / "offline"))
    CaseStore(tmp_path / "cases").save(case)
    return tmp_path


def test_cli_export_and_list(env: Path, case: Case) -> None:
    result = runner.invoke(app, ["offline", "export", case.id, "--retries", "0"])
    assert result.exit_code == 0, result.output
    pack_path = env / "offline" / "cases" / f"{case.id}.json"
    pack = OfflinePack.model_validate_json(pack_path.read_text(encoding="utf-8"))
    assert pack.case.id == case.id
    index = OfflineIndex.model_validate_json((env / "offline" / "index.json").read_text("utf-8"))
    assert [c.id for c in index.cases] == [case.id]
    assert index.cases[0].contradictions == 2

    result = runner.invoke(app, ["offline", "list"])
    assert result.exit_code == 0 and case.id in result.output
    assert runner.invoke(app, ["offline", "export", "nothing"]).exit_code == 1


def test_openapi_includes_offline_types(tmp_path: Path) -> None:
    schemas = create_app().openapi()["components"]["schemas"]
    assert {"OfflinePack", "OfflineIndex", "OfflineResponse", "CasePublic"} <= set(schemas)
    assert schemas["OfflinePack"]["properties"]["explanation"] == {
        "$ref": "#/components/schemas/Explanation"
    }
