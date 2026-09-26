from pathlib import Path

import pytest
from typer.testing import CliRunner

from llm_court.cli.main import app
from llm_court.domain import ResearchReport
from llm_court.llm.client import BackendFactory
from tests.fakes import FakeChatBackend, FakeError, FakeResponse

BACKEND_ROOT = Path(__file__).resolve().parents[2]
runner = CliRunner()


def test_help() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "config" in result.output


def test_config_check_ok() -> None:
    result = runner.invoke(
        app, ["config", "check", "--path", str(BACKEND_ROOT / "config" / "models.yaml")]
    )
    assert result.exit_code == 0, result.output
    assert "OK" in result.output


def test_config_check_error(tmp_path: Path) -> None:
    bad = tmp_path / "models.yaml"
    bad.write_text("providers: {}\nmodels: {}\nroles: {}\n", encoding="utf-8")
    result = runner.invoke(app, ["config", "check", "--path", str(bad)])
    assert result.exit_code == 1
    assert "設定エラー" in result.output


def _factory(fake: FakeChatBackend) -> BackendFactory:
    return lambda _provider: fake


def test_bench_with_fake_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    from llm_court.cli import main as cli_main
    from tests.unit.test_bench import bench_responder

    fake = FakeChatBackend(responder=bench_responder)
    monkeypatch.setattr(cli_main, "backend_factory", _factory(fake))
    monkeypatch.setenv("COLUMNS", "200")  # 表が切り詰められないように
    monkeypatch.setenv("LLM_COURT_MODELS_CONFIG_PATH", str(BACKEND_ROOT / "config/models.yaml"))
    monkeypatch.setenv("LLM_COURT_PROMPTS_DIR", str(BACKEND_ROOT / "prompts"))
    result = runner.invoke(app, ["bench", "--n", "1", "--role", "debater"])
    assert result.exit_code == 0, result.output
    assert "LLM ベンチマーク" in result.output
    assert "構造化出力" in result.output
    assert "1/1 (100%)" in result.output
    assert len(fake.requests) == 2


def test_bench_connection_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from llm_court.cli import main as cli_main

    fake = FakeChatBackend(
        responder=lambda _r: FakeResponse(error=FakeError(kind="connection", message="down"))
    )
    monkeypatch.setattr(cli_main, "backend_factory", _factory(fake))
    monkeypatch.setenv("LLM_COURT_MODELS_CONFIG_PATH", str(BACKEND_ROOT / "config/models.yaml"))
    monkeypatch.setenv("LLM_COURT_PROMPTS_DIR", str(BACKEND_ROOT / "prompts"))
    result = runner.invoke(app, ["bench", "--n", "1", "--role", "debater"])
    assert result.exit_code == 1
    assert "接続エラー" in result.output


def test_research_with_fakes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import json

    import httpx

    from llm_court.cli import main as cli_main
    from llm_court.domain import ResearchReport
    from llm_court.llm import ChatRequest

    article = (BACKEND_ROOT / "tests/fixtures/research/article.html").read_bytes()

    def site(request: httpx.Request) -> httpx.Response:
        if request.url.host == "searx.test":
            results = [{"url": f"https://news{i}.example/a", "title": f"記事 {i}"} for i in (1, 2)]
            return httpx.Response(200, json={"results": results})
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, content=article, headers={"content-type": "text/html"})

    def llm(request: ChatRequest) -> FakeResponse:
        if "検索クエリを" in request.messages[-1].content:
            return FakeResponse.text('{"queries": ["ベーシックインカム 実験"]}')
        draft = {
            "relevant": True,
            "title": "ベーシックインカム実験",
            "summary": "実験の要約。",
            "key_facts": [
                {
                    "text": "2,000人に支給",
                    "quote": "無作為に選ばれた失業者2,000人に毎月一定額を支給",
                },
                {"text": "捏造", "quote": "就業日数が半減したと報告された"},
            ],
        }
        return FakeResponse.text(json.dumps(draft, ensure_ascii=False))

    monkeypatch.setattr(cli_main, "backend_factory", _factory(FakeChatBackend(responder=llm)))
    monkeypatch.setattr(
        cli_main,
        "http_client_factory",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(site)),
    )
    monkeypatch.setenv("COLUMNS", "200")
    monkeypatch.setenv("LLM_COURT_MODELS_CONFIG_PATH", str(BACKEND_ROOT / "config/models.yaml"))
    monkeypatch.setenv("LLM_COURT_PROMPTS_DIR", str(BACKEND_ROOT / "prompts"))
    monkeypatch.setenv("LLM_COURT_SEARXNG_URL", "http://searx.test")
    monkeypatch.setenv("LLM_COURT_RESEARCH__CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("LLM_COURT_RESEARCH__MIN_TEXT_CHARS", "50")
    out = tmp_path / "report.json"

    result = runner.invoke(app, ["research", "ベーシックインカム", "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert "EV-01" in result.output and "EV-02" in result.output
    assert "✓" in result.output and "未検証" in result.output
    assert "証拠品 2 件 / 事実 4 件(引用検証済み 2 件、50%)" in result.output
    report = ResearchReport.model_validate_json(out.read_text(encoding="utf-8"))
    assert len(report.evidence) == 2

    # 2 回目はキャッシュから読む
    result = runner.invoke(app, ["research", "ベーシックインカム", "--out", str(out)])
    assert "キャッシュから読み込んだページ: 2 件" in result.output


def test_research_search_unavailable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import httpx

    from llm_court.cli import main as cli_main

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    monkeypatch.setattr(
        cli_main,
        "backend_factory",
        _factory(FakeChatBackend(responder=lambda _r: FakeResponse.text('{"queries": ["q"]}'))),
    )
    monkeypatch.setattr(
        cli_main,
        "http_client_factory",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(down)),
    )
    monkeypatch.setenv("LLM_COURT_MODELS_CONFIG_PATH", str(BACKEND_ROOT / "config/models.yaml"))
    monkeypatch.setenv("LLM_COURT_PROMPTS_DIR", str(BACKEND_ROOT / "prompts"))
    result = runner.invoke(app, ["research", "テーマ", "--out", str(tmp_path / "r.json")])
    assert result.exit_code == 1
    assert "接続エラー" in result.output


def test_debate_with_evidence_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, research_report: ResearchReport
) -> None:
    from llm_court.cli import main as cli_main
    from llm_court.engine.store import load_jsonl
    from tests.debate_fakes import DebateResponder

    evidence = tmp_path / "research.json"
    evidence.write_text(research_report.model_dump_json(), encoding="utf-8")

    monkeypatch.setattr(
        cli_main, "backend_factory", _factory(FakeChatBackend(responder=DebateResponder()))
    )
    monkeypatch.setenv("COLUMNS", "200")
    monkeypatch.setenv("LLM_COURT_MODELS_CONFIG_PATH", str(BACKEND_ROOT / "config/models.yaml"))
    monkeypatch.setenv("LLM_COURT_PROMPTS_DIR", str(BACKEND_ROOT / "prompts"))
    monkeypatch.setenv("LLM_COURT_DATABASE_PATH", str(tmp_path / "db.sqlite"))
    monkeypatch.setenv("LLM_COURT_DEBATE_OUTPUT_DIR", str(tmp_path / "debates"))

    result = runner.invoke(app, ["debate", "論題", "--rounds", "1", "--evidence", str(evidence)])
    assert result.exit_code == 0, result.output
    for text in (
        "冒頭陳述",
        "反論 第1回",
        "最終弁論",
        "【肯定側】",
        "判決: 肯定側の勝ち",
        "ターンごとの計測",
    ):
        assert text in result.output
    assert "EV-09 は存在しない証拠品です" in result.output

    jsonl = next((tmp_path / "debates").glob("*.jsonl"))
    events = load_jsonl(jsonl)
    assert events[0].type == "session_started"
    assert events[-1].type == "verdict_delivered"
    assert jsonl.with_suffix(".md").read_text(encoding="utf-8").startswith("# 法廷記録")


def test_debate_rejects_bad_evidence_file(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{}", encoding="utf-8")
    result = runner.invoke(app, ["debate", "論題", "--evidence", str(bad)])
    assert result.exit_code == 1
    assert "捜査結果を読み込めません" in result.output


def test_eval_command(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, research_report: ResearchReport
) -> None:
    from llm_court.cli import main as cli_main
    from tests.debate_fakes import DebateResponder

    evidence = tmp_path / "evidence.json"
    evidence.write_text(research_report.model_dump_json(), encoding="utf-8")
    models = BACKEND_ROOT / "config/models.yaml"
    spec = tmp_path / "spec.yaml"
    spec.write_text(
        f"""
name: CLI テスト
judge_repeats: 1
configs:
  - {{name: A, models: {models}}}
  - {{name: B, models: {models}}}
topics:
  - {{topic: 論題, evidence: {evidence}}}
""",
        encoding="utf-8",
    )
    fake = FakeChatBackend(responder=DebateResponder())
    monkeypatch.setattr(cli_main, "backend_factory", _factory(fake))
    monkeypatch.setenv("COLUMNS", "200")
    monkeypatch.setenv("LLM_COURT_PROMPTS_DIR", str(BACKEND_ROOT / "prompts"))
    out = tmp_path / "out"

    result = runner.invoke(app, ["eval", str(spec), "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert "構成の比較" in result.output
    assert "順序反転率" in result.output
    assert (out / "report.md").read_text(encoding="utf-8").startswith("# 評価レポート: CLI テスト")
    for name in ("runs.csv", "turns.csv", "summary.csv", "result.json", "events.db"):
        assert (out / name).exists()

    # 保存済みの結果から作り直したレポートは同じ内容になる
    before = (out / "report.md").read_text(encoding="utf-8")
    (out / "report.md").unlink()
    result = runner.invoke(app, ["eval-report", str(out)])
    assert result.exit_code == 0, result.output
    assert (out / "report.md").read_text(encoding="utf-8") == before


def test_eval_report_missing_dir(tmp_path: Path) -> None:
    result = runner.invoke(app, ["eval-report", str(tmp_path / "nope")])
    assert result.exit_code == 1
    assert "評価結果を読み込めません" in result.output


def test_eval_command_invalid_spec(tmp_path: Path) -> None:
    spec = tmp_path / "spec.yaml"
    spec.write_text("name: x\nconfigs: []\n", encoding="utf-8")
    result = runner.invoke(app, ["eval", str(spec)])
    assert result.exit_code == 1
    assert "評価仕様のエラー" in result.output


def test_openapi_command(tmp_path: Path) -> None:
    import json

    out = tmp_path / "openapi.json"
    result = runner.invoke(app, ["openapi", "--out", str(out)])
    assert result.exit_code == 0, result.output
    schema = json.loads(out.read_text(encoding="utf-8"))
    assert schema["info"]["title"] == "llm-court API"
    assert "/api/sessions" in schema["paths"]
