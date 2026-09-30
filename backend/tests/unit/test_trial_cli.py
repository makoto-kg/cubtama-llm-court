import csv
from pathlib import Path

import pytest
from typer.testing import CliRunner

from llm_court.cli import main as cli_main
from llm_court.cli import trial as trial_cli
from llm_court.cli.main import app
from llm_court.domain import Case, ResearchReport
from llm_court.engine.store import load_jsonl
from llm_court.eval.trial_eval import ResponseRow, deviation_metrics
from llm_court.llm import PromptLoader
from llm_court.llm.client import BackendFactory
from llm_court.scenario.store import CaseStore
from tests.fakes import FakeChatBackend
from tests.trial_fakes import TrialResponder, make_case

BACKEND_ROOT = Path(__file__).resolve().parents[2]
runner = CliRunner()


@pytest.fixture
async def case(prompts: PromptLoader, research_report: ResearchReport) -> Case:
    return await make_case(prompts, research_report)


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, case: Case) -> Path:
    fake = FakeChatBackend(responder=TrialResponder())
    factory: BackendFactory = lambda _p: fake  # noqa: E731
    monkeypatch.setattr(cli_main, "backend_factory", factory)
    monkeypatch.setenv("COLUMNS", "200")
    monkeypatch.setenv("LLM_COURT_MODELS_CONFIG_PATH", str(BACKEND_ROOT / "config/models.yaml"))
    monkeypatch.setenv("LLM_COURT_PROMPTS_DIR", str(BACKEND_ROOT / "prompts"))
    monkeypatch.setenv("LLM_COURT_DATABASE_PATH", str(tmp_path / "db.sqlite"))
    monkeypatch.setenv("LLM_COURT_DEBATE_OUTPUT_DIR", str(tmp_path / "debates"))
    monkeypatch.setenv("LLM_COURT_EVAL_OUTPUT_DIR", str(tmp_path / "eval"))
    monkeypatch.setenv("LLM_COURT_SCENARIO__CASE_DIR", str(tmp_path / "cases"))
    CaseStore(tmp_path / "cases").save(case)
    return tmp_path


def scripted_ask(answers: list[str]) -> trial_cli.AskFn:
    """答えを順に返す。尽きたら常に先頭の選択肢(1)を選ぶ。"""
    queue = list(answers)

    async def ask(question: str, choices: list[str]) -> str:
        answer = queue.pop(0) if queue else "1"
        assert answer in choices
        return answer

    return ask


def test_trial_plays_to_explanation(env: Path, case: Case, monkeypatch: pytest.MonkeyPatch) -> None:
    # 先頭の選択肢を選び続ける(罠・はずれで減点されても、いずれ閉廷する)
    monkeypatch.setattr(trial_cli, "_ask", scripted_ask(["e"]))
    result = runner.invoke(app, ["trial", case.id, "--reveal"])
    assert result.exit_code == 0, result.output
    out = result.output
    assert case.title in out
    assert "ペナルティゲージ" in out
    assert "つきつける" in out
    assert "証拠品" in out
    assert "閉廷" in out and "解説" in out
    assert "出典:" in out and "真相" in out
    jsonl = next((env / "debates").glob("trial-*.jsonl"))
    events = load_jsonl(jsonl)
    assert events[0].type == "trial_started"
    assert events[-1].type in ("trial_finished", "llm_call_recorded")


def test_trial_quit_and_resume(env: Path, case: Case, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(trial_cli, "_ask", scripted_ask(["q"]))
    result = runner.invoke(app, ["trial", case.id])
    assert result.exit_code == 0, result.output
    assert "llm-court trial --resume" in result.output
    session_id = result.output.split("--resume ")[1].split()[0]

    monkeypatch.setattr(trial_cli, "_ask", scripted_ask([]))
    result = runner.invoke(app, ["trial", "--resume", session_id])
    assert result.exit_code == 0, result.output
    assert "再開" in result.output and "閉廷" in result.output


def test_trial_requires_case(env: Path) -> None:
    assert runner.invoke(app, ["trial"]).exit_code == 2
    assert runner.invoke(app, ["trial", "nothing"]).exit_code == 1


def test_eval_trial_report(env: Path, case: Case) -> None:
    out = env / "eval-out"
    result = runner.invoke(app, ["eval-trial", case.id, "--runs", "2", "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert "被告の台本逸脱率" in result.output
    report = (out / "report.md").read_text(encoding="utf-8")
    assert "| 全体 |" in report and "逸脱した応答" not in report
    with (out / "responses.csv").open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    actions = {r["action"] for r in rows}
    assert actions == {"probe", "weak", "trap", "strong"}
    assert sum(r["action"] == "strong" for r in rows) == 2 * len(case.contradictions)
    assert all(r["deviations"] == "" for r in rows)
    assert len(list(out.glob("*.jsonl"))) == 2


def row(**kwargs: object) -> ResponseRow:
    base: dict[str, object] = {
        "case_id": "c",
        "run": 1,
        "session_id": "s",
        "option_id": "Q01-1",
        "action": "probe",
        "label": "l",
        "should_collapse": False,
        "checked": True,
        "confessed": False,
        "leaked": 0,
        "deviations": [],
        "reason": "r",
        "text": "t",
        "witness_ms": 1000.0,
    }
    return ResponseRow.model_validate(base | kwargs)


def test_deviation_metrics() -> None:
    rows = [
        row(),
        row(confessed=True, deviations=["premature_confession", "leak"], leaked=1),
        row(action="strong", should_collapse=True, confessed=False, deviations=["failed_collapse"]),
        row(action="strong", should_collapse=True, confessed=True),
        row(checked=False, confessed=None),
    ]
    m = deviation_metrics("全体", rows)
    assert m.responses == 5 and m.checked == 4
    assert m.premature_confession_rate == 0.5
    assert m.leak_rate == 0.5
    assert m.failed_collapse_rate == 0.5
    assert m.deviation_rate == 0.5
    assert m.witness_p50_s == 1.0
    empty = deviation_metrics("なし", [])
    assert empty.deviation_rate is None and empty.witness_p50_s is None
