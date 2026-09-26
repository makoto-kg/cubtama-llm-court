import csv
from pathlib import Path

import pytest
import yaml

from llm_court.config import ModelsConfig
from llm_court.domain import ResearchReport
from llm_court.engine.recorder import BufferedRecorder
from llm_court.eval.harness import EvalHarness
from llm_court.eval.metrics import config_metrics
from llm_court.eval.models import EvalResult
from llm_court.eval.report import write_report
from llm_court.eval.spec import EvalConfig, EvalSpec, EvalTopic
from llm_court.llm import ChatRequest, LLMClient, LLMConnectionError, PromptLoader
from llm_court.modes import DEBATE_MODE
from tests.debate_fakes import DebateResponder
from tests.fakes import FakeChatBackend, FakeError, FakeResponse
from tests.unit.test_llm_client import make_config

BACKEND_ROOT = Path(__file__).resolve().parents[2]


class Backends:
    """モデル設定ファイルの名前ごとに応答を切り替えるフェイク。"""

    def __init__(self) -> None:
        self.by_model: dict[str, FakeChatBackend] = {
            "good": FakeChatBackend(responder=DebateResponder()),
            # 論者が何も話さない構成(毎回中断する)
            "silent": FakeChatBackend(responder=lambda _r: FakeResponse.text("")),
            "reference": FakeChatBackend(responder=DebateResponder(judge_scores=[(5, 7), (5, 7)])),
        }

    def factory(self, prompts: PromptLoader):
        def make(models: ModelsConfig, recorder: BufferedRecorder) -> LLMClient:
            key = models.models["fast"].model
            backend = self.by_model[key]
            return LLMClient(
                models,
                prompts=prompts,
                structured_max_retries=0,
                backend_factory=lambda _p: backend,
                recorder=recorder,
            )

        return make


def models_file(tmp_path: Path, name: str) -> Path:
    config = make_config()
    data = config.model_dump(mode="json")
    data["models"]["fast"]["model"] = name
    data["models"]["heavy"]["model"] = name
    data["providers"]["local"]["api_key"] = "x"
    path = tmp_path / f"{name}.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


def make_spec(
    tmp_path: Path, research_report: ResearchReport, configs: list[str], **kwargs: object
) -> EvalSpec:
    evidence = tmp_path / "evidence.json"
    evidence.write_text(research_report.model_dump_json(), encoding="utf-8")
    return EvalSpec.model_validate(
        {
            "name": "テスト評価",
            "rounds": 1,
            "runs": 2,
            "judge_repeats": 2,
            "configs": [
                EvalConfig(name=c, models=models_file(tmp_path, c)).model_dump() for c in configs
            ],
            "topics": [EvalTopic(topic="論題A", evidence=evidence).model_dump()],
            **kwargs,
        }
    )


async def run_harness(
    tmp_path: Path, prompts: PromptLoader, spec: EvalSpec, backends: Backends
) -> EvalResult:
    harness = EvalHarness(
        prompts=prompts,
        mode=DEBATE_MODE,
        client_factory=backends.factory(prompts),
        out_dir=tmp_path / "out",
    )
    return await harness.run(spec)


async def test_harness_two_configs(
    tmp_path: Path, prompts: PromptLoader, research_report: ResearchReport
) -> None:
    backends = Backends()
    spec = make_spec(tmp_path, research_report, ["good", "silent"])
    result = await run_harness(tmp_path, prompts, spec, backends)

    assert [(r.config, r.run) for r in result.runs] == [
        ("good", 1),
        ("good", 2),
        ("silent", 1),
        ("silent", 2),
    ]
    good = [r for r in result.runs if r.config == "good"]
    assert all(r.error is None for r in good)
    # ディベート中の判決 + 再評価 2 回(それぞれ提示順 2 つ)
    assert [j.source for j in good[0].judgings] == ["debate", "repeat", "repeat"]
    assert all(len(j.scores) == 2 for j in good[0].judgings)
    assert len(good[0].judge_calls) == 4  # 再評価 2 回 × 提示順 2 つ
    assert result.configs["good"]["judge"] == "good"

    silent = [r for r in result.runs if r.config == "silent"]
    assert all(r.error and "発言が空" in r.error for r in silent)
    assert all(r.judgings == [] for r in silent)

    # ディベートのログは JSONL に残る
    assert len(list((tmp_path / "out" / "debates").glob("*.jsonl"))) == 4

    m_good = config_metrics("good", good, DEBATE_MODE)
    assert (m_good.debates, m_good.completed, m_good.aborted) == (2, 2, 0)
    assert m_good.order_flip_rate == 0
    assert m_good.repeat_stability == 1
    assert m_good.margin_stdev == 0
    assert m_good.reference_agreement is None
    assert m_good.verdicts == {"affirmative": 2}
    # 否定側は毎回 EV-09(存在しない)を引く: 出典 6 件中 3 件(1 ディベートあたり)
    assert m_good.unknown_evidence_rate == pytest.approx(6 / 18)
    assert m_good.citations.checked_quotes == 12
    assert m_good.unsupported_quote_rate == 0
    assert m_good.no_citation_rate == 0
    assert m_good.structured_failure_rate == 0
    assert set(m_good.structured_by_role) == {"claim_extractor", "judge"}
    assert m_good.structured_by_role["judge"].calls == 12  # (判決 2 + 再評価 4) × 2 回
    assert m_good.turn_p50_s is not None
    assert m_good.length_ratio is not None and m_good.length_ratio < 1

    m_silent = config_metrics("silent", silent, DEBATE_MODE)
    assert (m_silent.completed, m_silent.aborted) == (0, 2)
    assert m_silent.order_flip_rate is None
    assert m_silent.verdicts == {}


async def test_harness_reference_judge(
    tmp_path: Path, prompts: PromptLoader, research_report: ResearchReport
) -> None:
    backends = Backends()
    spec = make_spec(
        tmp_path,
        research_report,
        ["good"],
        runs=1,
        judge_repeats=0,
        reference_judge=models_file(tmp_path, "reference"),
    )
    result = await run_harness(tmp_path, prompts, spec, backends)
    (run,) = result.runs
    assert [j.source for j in run.judgings] == ["debate", "reference"]
    assert result.reference_judge == "reference"
    # 参照用裁判長だけが呼ばれている(論者などは呼ばれない)
    reference_requests: list[ChatRequest] = backends.by_model["reference"].requests
    assert len(reference_requests) == 2
    assert all(r.response_format is not None for r in reference_requests)

    metrics = config_metrics("good", result.runs, DEBATE_MODE)
    assert metrics.reference_agreement == 0  # 自前は肯定側、参照は否定側


async def test_harness_rejudge_failure_is_skipped(
    tmp_path: Path, prompts: PromptLoader, research_report: ResearchReport
) -> None:
    backends = Backends()
    responder = DebateResponder()
    judge_calls = 0

    def flaky(request: ChatRequest) -> FakeResponse:
        nonlocal judge_calls
        if (
            request.response_format
            and request.response_format["json_schema"]["name"] == "JudgeOutput"
        ):
            judge_calls += 1
            if judge_calls > 2:  # ディベート中の判決(2 回)の後の再評価は壊れた JSON
                return FakeResponse.text("壊れた出力")
        return responder(request)

    backends.by_model["good"] = FakeChatBackend(responder=flaky)
    spec = make_spec(tmp_path, research_report, ["good"], runs=1, judge_repeats=1)
    (run,) = (await run_harness(tmp_path, prompts, spec, backends)).runs
    assert [j.source for j in run.judgings] == ["debate"]
    assert any(not c.success for c in run.judge_calls)


async def test_harness_stops_on_connection_error(
    tmp_path: Path, prompts: PromptLoader, research_report: ResearchReport
) -> None:
    backends = Backends()
    backends.by_model["good"] = FakeChatBackend(
        responder=lambda _r: FakeResponse(error=FakeError(kind="connection", message="down"))
    )
    spec = make_spec(tmp_path, research_report, ["good"], runs=1)
    with pytest.raises(LLMConnectionError):
        await run_harness(tmp_path, prompts, spec, backends)


async def test_write_report(
    tmp_path: Path, prompts: PromptLoader, research_report: ResearchReport
) -> None:
    backends = Backends()
    spec = make_spec(
        tmp_path,
        research_report,
        ["good", "silent"],
        reference_judge=models_file(tmp_path, "reference"),
    )
    result = await run_harness(tmp_path, prompts, spec, backends)
    metrics = [
        config_metrics(c.name, [r for r in result.runs if r.config == c.name], DEBATE_MODE)
        for c in spec.configs
    ]
    files = write_report(result, metrics, tmp_path / "report")

    with files.runs_csv.open(encoding="utf-8") as f:
        runs = list(csv.DictReader(f))
    assert [r["status"] for r in runs] == ["completed", "completed", "aborted", "aborted"]
    assert runs[0]["verdict"] == "affirmative"
    assert runs[0]["repeat_verdicts"] == "affirmative;affirmative"
    assert runs[0]["reference_verdict"] == "negative"
    assert runs[0]["unknown_evidence"] == "3"
    assert "発言が空" in runs[2]["error"]

    with files.turns_csv.open(encoding="utf-8") as f:
        turns = list(csv.DictReader(f))
    assert len(turns) == 12  # 完了した 2 回 × 6 発言(中断した回は 0 発言)
    assert turns[0]["phase"] == "opening"

    with files.summary_csv.open(encoding="utf-8") as f:
        summary = list(csv.DictReader(f))
    assert [s["config"] for s in summary] == ["good", "silent"]
    assert summary[0]["verdicts_affirmative"] == "2"
    assert summary[0]["reference_agreement"] == "0.0"

    md = files.markdown.read_text(encoding="utf-8")
    assert md.startswith("# 評価レポート: テスト評価")
    assert "| 指標 | good | silent |" in md
    assert "| 順序反転率 ↓ | 0% | - |" in md
    assert "| ディベート数(完了 / 中断) | 2(2 / 0) | 2(0 / 2) |" in md
    assert "| 参照用裁判長との一致率 ↑ | 0% | - |" in md
    assert "| silent | 論題A | 1 | 中断 |" in md

    result_json = files.result_json.read_text(encoding="utf-8")
    assert '"events"' not in result_json
    assert EvalResult.model_validate_json(result_json).runs[0].events == []


async def test_harness_analyst_eval(
    tmp_path: Path, prompts: PromptLoader, research_report: ResearchReport
) -> None:
    backends = Backends()
    spec = make_spec(tmp_path, research_report, ["good"], runs=1, judge_repeats=0, analyst=True)
    result = await run_harness(tmp_path, prompts, spec, backends)
    (run,) = result.runs
    # 反論 2 + 最終弁論 2 の発言それぞれに候補セット
    assert [s.statement_id for s in run.analyst] == ["S-03", "S-04", "S-05", "S-06"]
    assert all(s.success and s.discarded == 1 for s in run.analyst)
    # 否定側の発言は架空の証拠品 EV-09 を引くので、機械検査の候補が加わる
    rule = {s.statement_id: [c for c in s.candidates if c.source == "rule"] for s in run.analyst}
    assert [len(rule[i]) for i in ("S-03", "S-04", "S-05", "S-06")] == [0, 1, 0, 1]

    metrics = config_metrics("good", result.runs, DEBATE_MODE)
    stats = metrics.analyst
    assert stats is not None
    assert stats.sets == 4
    assert stats.success_rate == 1
    assert stats.trap_inclusion_rate == 1
    assert stats.strengths == {"strong": 4, "weak": 4, "trap": 4}
    assert stats.invalid_reference_rate == pytest.approx(4 / 16)
    assert stats.strong_validity == 1
    assert stats.trap_agreement == 0  # 検証役は trap を weak と判定する
    assert stats.verified == 12
    assert stats.rule_candidates == 2

    files = write_report(result, [metrics], tmp_path / "report")
    md = files.markdown.read_text(encoding="utf-8")
    assert "### 分析官" in md
    assert "| 罠の混入率 | 100% |" in md
    assert "| 強さの分布(strong / weak / trap) | 4 / 4 / 4 |" in md
    with files.summary_csv.open(encoding="utf-8") as f:
        row = next(csv.DictReader(f))
    assert row["analyst_trap_agreement"] == "0.0"


async def test_harness_without_analyst_has_no_section(
    tmp_path: Path, prompts: PromptLoader, research_report: ResearchReport
) -> None:
    spec = make_spec(tmp_path, research_report, ["good"], runs=1, judge_repeats=0)
    result = await run_harness(tmp_path, prompts, spec, Backends())
    metrics = config_metrics("good", result.runs, DEBATE_MODE)
    assert metrics.analyst is None
    md = write_report(result, [metrics], tmp_path / "report").markdown.read_text(encoding="utf-8")
    assert "### 分析官" not in md
