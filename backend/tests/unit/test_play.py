import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from llm_court.cli import main as cli_main
from llm_court.cli.main import app
from llm_court.cli.play import gauge_bar
from llm_court.domain import ResearchReport
from llm_court.engine.store import load_jsonl
from llm_court.llm.client import BackendFactory
from tests.debate_fakes import DebateResponder
from tests.fakes import FakeChatBackend

BACKEND_ROOT = Path(__file__).resolve().parents[2]
runner = CliRunner()


@pytest.fixture
def evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, research_report: ResearchReport
) -> Path:
    fake = FakeChatBackend(responder=DebateResponder())
    factory: BackendFactory = lambda _p: fake  # noqa: E731
    monkeypatch.setattr(cli_main, "backend_factory", factory)
    monkeypatch.setenv("COLUMNS", "200")
    monkeypatch.setenv("LLM_COURT_MODELS_CONFIG_PATH", str(BACKEND_ROOT / "config/models.yaml"))
    monkeypatch.setenv("LLM_COURT_PROMPTS_DIR", str(BACKEND_ROOT / "prompts"))
    monkeypatch.setenv("LLM_COURT_DATABASE_PATH", str(tmp_path / "db.sqlite"))
    monkeypatch.setenv("LLM_COURT_DEBATE_OUTPUT_DIR", str(tmp_path / "debates"))
    path = tmp_path / "research.json"
    path.write_text(research_report.model_dump_json(), encoding="utf-8")
    return path


def test_gauge_bar() -> None:
    assert gauge_bar(3, 5) == "■■■□□ 3/5"
    assert gauge_bar(-1, 5) == "□□□□□ 0/5"


def test_play_full_game(evidence: Path, tmp_path: Path) -> None:
    # 冒頭陳述の方針 → 反論(2 番目の候補)→ 最終弁論の方針
    result = runner.invoke(app, ["play", "論題", "--evidence", str(evidence)], input="1\n2\n1\n")
    assert result.exit_code == 0, result.output
    out = result.output
    assert out.count("あなたの番(否定側") == 3
    assert "ペナルティゲージ: ■■■■■ 5/5" in out
    assert "つきつける" in out and "ゆさぶる" in out and "方針" in out
    assert "選んだ指摘の強さ:" in out
    assert "結果:" in out
    # --reveal なしでは強さ・判断理由の列を出さない
    assert "判断理由" not in out.split("あなたの番")[2].split("番号を選んでください")[0]

    jsonl = next((tmp_path / "debates").glob("*.jsonl"))
    events = load_jsonl(jsonl)
    assert sum(e.type == "choice_made" for e in events) == 3
    assert events[-1].type == "verdict_delivered"


def test_play_reveal_shows_strength(evidence: Path) -> None:
    result = runner.invoke(
        app, ["play", "論題", "--evidence", str(evidence), "--reveal"], input="1\n1\n1\n"
    )
    assert result.exit_code == 0, result.output
    rebuttal = result.output.split("あなたの番")[2]
    assert "strong" in rebuttal and "trap" in rebuttal
    assert "判断理由" in rebuttal


def test_play_quit_and_resume(evidence: Path) -> None:
    result = runner.invoke(app, ["play", "論題", "--evidence", str(evidence)], input="q\n")
    assert result.exit_code == 0, result.output
    match = re.search(r"llm-court play --resume (\w+)", result.output)
    assert match is not None
    session_id = match.group(1)

    # 無効な入力は聞き直される
    result = runner.invoke(app, ["play", "--resume", session_id], input="9\n1\n1\n1\n")
    assert result.exit_code == 0, result.output
    assert "再開: 論題(否定側)" in result.output
    assert "結果:" in result.output


def test_play_requires_topic_or_resume() -> None:
    result = runner.invoke(app, ["play"])
    assert result.exit_code == 2
    assert "論題を指定するか" in result.output


def test_play_resume_llm_session_is_error(evidence: Path) -> None:
    result = runner.invoke(app, ["debate", "論題", "--rounds", "1", "--evidence", str(evidence)])
    assert result.exit_code == 0, result.output
    session_id = re.search(r"debates/(\w+)\.jsonl", result.output)
    assert session_id is not None
    result = runner.invoke(app, ["play", "--resume", session_id.group(1)])
    assert result.exit_code == 1
    assert "人間が参加していない" in result.output
