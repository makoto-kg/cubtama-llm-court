import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from llm_court.cli import main as cli_main
from llm_court.cli.main import app
from llm_court.domain import ResearchReport
from llm_court.llm.client import BackendFactory
from llm_court.scenario.store import CaseStore
from tests.case_fakes import UNSOLVED, CaseResponder, text
from tests.fakes import FakeChatBackend

BACKEND_ROOT = Path(__file__).resolve().parents[2]
runner = CliRunner()


def setup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, responder: CaseResponder) -> None:
    fake = FakeChatBackend(responder=responder)
    factory: BackendFactory = lambda _p: fake  # noqa: E731
    monkeypatch.setattr(cli_main, "backend_factory", factory)
    monkeypatch.setenv("COLUMNS", "200")
    monkeypatch.setenv("LLM_COURT_MODELS_CONFIG_PATH", str(BACKEND_ROOT / "config/models.yaml"))
    monkeypatch.setenv("LLM_COURT_PROMPTS_DIR", str(BACKEND_ROOT / "prompts"))
    monkeypatch.setenv("LLM_COURT_SCENARIO__CASE_DIR", str(tmp_path / "cases"))


@pytest.fixture
def evidence(tmp_path: Path, research_report: ResearchReport) -> Path:
    path = tmp_path / "research.json"
    path.write_text(research_report.model_dump_json(), encoding="utf-8")
    return path


def test_generate_list_validate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, evidence: Path
) -> None:
    setup(monkeypatch, tmp_path, CaseResponder())
    result = runner.invoke(app, ["case", "generate", "給付", "--evidence", str(evidence)])
    assert result.exit_code == 0, result.output
    out = result.output
    assert "給付事業報告書事件" in out
    assert "LP-01" in out and "X-01" in out
    assert "検証: 解ける / 一意 / 最短 2 手 / 解答率 100%(2 回中)" in out
    case_id = re.search(r"cases/(\w+)\.json", out)
    assert case_id is not None

    result = runner.invoke(app, ["case", "list"])
    assert result.exit_code == 0
    assert case_id.group(1) in result.output and "解ける" in result.output

    result = runner.invoke(app, ["case", "validate", case_id.group(1)])
    assert result.exit_code == 0, result.output
    assert "solver 1: 矛盾 2/2" in result.output
    stored = CaseStore(tmp_path / "cases").load(case_id.group(1))
    assert stored.validation is not None and stored.validation.solved


def test_generate_unsolvable_is_saved_but_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, evidence: Path
) -> None:
    monkeypatch.setenv("LLM_COURT_SCENARIO__MAX_REGENERATIONS", "0")
    setup(monkeypatch, tmp_path, CaseResponder({"SolverOutput": lambda _n, _r: text(UNSOLVED)}))
    result = runner.invoke(app, ["case", "generate", "給付", "--evidence", str(evidence)])
    assert result.exit_code == 1
    assert "解けない" in result.output
    assert len(CaseStore(tmp_path / "cases").list()) == 1


def test_validate_unknown_case(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    setup(monkeypatch, tmp_path, CaseResponder())
    result = runner.invoke(app, ["case", "validate", "nope"])
    assert result.exit_code == 1
    assert "ありません" in result.output
    assert "まだありません" in runner.invoke(app, ["case", "list"]).output
