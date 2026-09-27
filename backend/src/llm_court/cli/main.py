"""llm-court CLI のエントリポイント。"""

import asyncio
import logging
import re
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Annotated

import httpx
import typer
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.prompt import Prompt
from rich.status import Status
from rich.table import Table

from llm_court.cli.case import case_app
from llm_court.cli.offline import offline_app
from llm_court.cli.play import PlayLoop
from llm_court.cli.trial import eval_trial, trial
from llm_court.config import ConfigError, ModelsConfig, Role, Settings, load_models_config
from llm_court.domain import (
    CitationIssuesDetected,
    ClaimsExtracted,
    Event,
    EvidenceCollected,
    JudgeScored,
    PhaseStarted,
    ResearchReport,
    SessionAborted,
    Side,
    StatementMade,
    VerdictDelivered,
)
from llm_court.engine.debate import DebateEngine, DebateObserver, SessionStateError
from llm_court.engine.record import render_markdown
from llm_court.engine.recorder import BufferedRecorder
from llm_court.engine.state import DebateState
from llm_court.engine.store import EventStore, export_jsonl
from llm_court.engine.summary import DebateSummary, summarize
from llm_court.eval.harness import EvalHarness
from llm_court.eval.metrics import ConfigMetrics
from llm_court.eval.models import EvalResult
from llm_court.eval.report import compute_metrics, load_result, write_report
from llm_court.eval.spec import EvalSpecError, load_spec
from llm_court.llm import InMemoryRecorder, LLMClient, LLMConnectionError, PromptLoader
from llm_court.llm.backend import OpenAIChatBackend
from llm_court.llm.bench import BenchRow, run_bench
from llm_court.llm.client import BackendFactory
from llm_court.llm.errors import LLMError
from llm_court.modes import DEBATE_MODE, Turn
from llm_court.research.cache import PageCache
from llm_court.research.fetch import PageFetcher
from llm_court.research.pipeline import ResearchPipeline
from llm_court.research.search import SearchError, SearXNGClient

app = typer.Typer(
    help="LLM 法廷バトルゲーム llm-court の CLI。",
    no_args_is_help=True,
)
config_app = typer.Typer(help="設定ファイルの確認。", no_args_is_help=True)
app.add_typer(config_app, name="config")
app.add_typer(case_app, name="case")
app.add_typer(offline_app, name="offline")
app.command("trial")(trial)
app.command("eval-trial")(eval_trial)

console = Console()

# テストでフェイクに差し替えるため、モジュール属性として持つ
backend_factory: BackendFactory = OpenAIChatBackend.from_provider
http_client_factory: Callable[[], httpx.AsyncClient] = httpx.AsyncClient


@app.callback()
def main() -> None:
    settings = Settings()
    logging.basicConfig(level=settings.log_level)
    # HTTP クライアントのリクエストごとのログは Rich の表示を埋めるので抑える
    for name in ("httpx", "httpx2", "httpcore", "httpcore2", "openai"):
        logging.getLogger(name).setLevel(logging.WARNING)
    # 本文抽出の失敗は除外理由として表示するので、trafilatura 自身の警告は出さない
    logging.getLogger("trafilatura").setLevel(logging.ERROR)


@config_app.command("check")
def config_check(
    path: Annotated[
        Path | None,
        typer.Option("--path", "-p", help="models.yaml のパス(既定は設定値)"),
    ] = None,
) -> None:
    """models.yaml を検証し、役割ごとのモデル割り当てを表示する。"""
    settings = Settings()
    target = path or settings.models_config_path
    try:
        config = load_models_config(target)
    except ConfigError as e:
        console.print(f"[red]設定エラー:[/red] {e}")
        raise typer.Exit(code=1) from e

    table = Table(title=f"役割の割り当て ({target})")
    table.add_column("役割")
    table.add_column("モデル")
    table.add_column("モデル ID")
    table.add_column("推論")
    table.add_column("プロバイダ")
    table.add_column("base_url")
    for role in Role:
        r = config.resolve(role)
        table.add_row(
            role.value,
            r.model_key,
            r.model.model,
            r.model.reasoning or "-",
            r.provider_key,
            r.provider.base_url,
        )
    console.print(table)
    console.print("[green]OK[/green] models.yaml は有効です")


def _fmt_ms(value: float | None) -> str:
    return "-" if value is None else f"{value / 1000:.1f}s"


def _fmt_num(value: float | None, digits: int = 1) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def _bench_table(rows: list[BenchRow]) -> Table:
    table = Table(title="LLM ベンチマーク")
    table.add_column("モデル")
    table.add_column("役割")
    table.add_column("タスク")
    table.add_column("成功率", justify="right")
    table.add_column("平均リトライ", justify="right")
    table.add_column("TTFT(中央値)", justify="right")
    table.add_column("総時間(中央値)", justify="right")
    table.add_column("tok/s(平均)", justify="right")
    table.add_column("モード")
    for row in rows:
        rate = f"{row.successes}/{row.runs} ({row.success_rate:.0%})"
        color = "green" if row.success_rate == 1 else "yellow" if row.successes else "red"
        table.add_row(
            f"{row.model}\n[dim]{row.model_key}[/dim]",
            ", ".join(row.roles),
            "自由生成" if row.task == "text" else "構造化出力",
            f"[{color}]{rate}[/{color}]",
            _fmt_num(row.mean_retries, 2),
            _fmt_ms(row.median_ttft_ms),
            _fmt_ms(row.median_total_ms),
            _fmt_num(row.mean_tokens_per_s),
            ", ".join(f"{k}×{v}" for k, v in row.modes.items()) or "-",
        )
    return table


@app.command()
def bench(
    n: Annotated[int, typer.Option("--n", "-n", min=1, help="タスクごとの実行回数")] = 3,
    roles: Annotated[
        list[Role] | None,
        typer.Option("--role", "-r", help="対象の役割(複数指定可。既定は全役割)"),
    ] = None,
) -> None:
    """各役割のモデルで日本語の自由生成と構造化出力を実行し、速度と成功率を表示する。"""
    settings = Settings()
    recorder = InMemoryRecorder()
    try:
        client = LLMClient.from_settings(
            settings, backend_factory=backend_factory, recorder=recorder
        )
    except ConfigError as e:
        console.print(f"[red]設定エラー:[/red] {e}")
        raise typer.Exit(code=1) from e
    prompts = PromptLoader(settings.prompts_dir)
    targets = roles or list(Role)

    async def run() -> list[BenchRow]:
        async with client:
            with console.status("ベンチマーク実行中…") as status:
                return await run_bench(
                    client,
                    recorder,
                    prompts,
                    targets,
                    n,
                    on_progress=lambda msg: status.update(f"実行中: {msg}"),
                )

    try:
        rows = asyncio.run(run())
    except LLMConnectionError as e:
        console.print(f"[red]接続エラー:[/red] {e}")
        raise typer.Exit(code=1) from e

    console.print(_bench_table(rows))
    for row in rows:
        for error in dict.fromkeys(row.errors):
            console.print(f"[yellow]{row.model} / {row.task}:[/yellow] {error}")


def _slug(text: str, limit: int = 40) -> str:
    slug = re.sub(r"[^\w]+", "-", text).strip("-")
    return slug[:limit] or "topic"


def _print_report(report: ResearchReport) -> None:
    console.rule(f"捜査結果: {escape(report.topic)}")
    console.print(f"[dim]検索クエリ: {escape(' / '.join(report.queries))}[/dim]\n")
    for ev in report.evidence:
        date = f" [dim]({ev.published_date})[/dim]" if ev.published_date else ""
        console.print(f"[bold cyan]{ev.id}[/bold cyan] [bold]{escape(ev.title)}[/bold]{date}")
        console.print(f"  [dim]{escape(ev.source_url)}[/dim]")
        console.print(f"  {escape(ev.summary)}")
        for fact in ev.key_facts:
            mark = "[green]✓[/green]" if fact.quote_verified else "[red]✗ 未検証[/red]"
            console.print(f"  {mark} {escape(fact.text)}")
            console.print(f"      [dim]「{escape(fact.quote)}」[/dim]")
        console.print()

    facts = [f for ev in report.evidence for f in ev.key_facts]
    verified = sum(f.quote_verified for f in facts)
    rate = f"{verified / len(facts):.0%}" if facts else "-"
    console.rule("集計")
    console.print(
        f"証拠品 {len(report.evidence)} 件 / 事実 {len(facts)} 件"
        f"(引用検証済み {verified} 件、{rate})"
    )
    if report.skipped:
        table = Table(title=f"除外した情報源({len(report.skipped)} 件)", show_lines=False)
        table.add_column("URL", overflow="fold")
        table.add_column("理由")
        for s in report.skipped:
            table.add_row(escape(s.url), escape(s.reason))
        console.print(table)


@app.command()
def research(
    topic: Annotated[str, typer.Argument(help="調べるテーマ")],
    out: Annotated[
        Path | None, typer.Option("--out", "-o", help="結果 JSON の保存先(既定は output_dir)")
    ] = None,
    max_evidence: Annotated[
        int | None, typer.Option("--max-evidence", "-m", min=1, help="証拠品の上限")
    ] = None,
    max_chars: Annotated[
        int | None,
        typer.Option("--max-chars", min=500, help="LLM に渡すページ本文の最大文字数(既定は設定値)"),
    ] = None,
) -> None:
    """テーマを Web で調べ、引用を検証した証拠品を作る。"""
    settings = Settings()
    overrides: dict[str, int] = {}
    if max_evidence is not None:
        overrides["target_evidence"] = max_evidence
    if max_chars is not None:
        overrides["max_chars_per_page"] = max_chars
    research_settings = settings.research.model_copy(update=overrides)
    try:
        client = LLMClient.from_settings(settings, backend_factory=backend_factory)
    except ConfigError as e:
        console.print(f"[red]設定エラー:[/red] {e}")
        raise typer.Exit(code=1) from e
    prompts = PromptLoader(settings.prompts_dir)

    async def run() -> tuple[ResearchReport, int]:
        async with client, http_client_factory() as http:
            fetcher = PageFetcher(
                research_settings, client=http, cache=PageCache(research_settings.cache_dir)
            )
            pipeline = ResearchPipeline(
                client,
                prompts,
                SearXNGClient(
                    settings.searxng_url, timeout_s=research_settings.fetch_timeout_s, client=http
                ),
                fetcher,
                research_settings,
            )
            with console.status("捜査中…") as status:
                report = await pipeline.run(topic, on_progress=lambda m: status.update(m))
            return report, fetcher.cache_hits

    try:
        report, cache_hits = asyncio.run(run())
    except (SearchError, LLMConnectionError) as e:
        console.print(f"[red]接続エラー:[/red] {e}")
        raise typer.Exit(code=1) from e
    except LLMError as e:
        console.print(f"[red]LLM エラー:[/red] {e}")
        raise typer.Exit(code=1) from e

    _print_report(report)
    if cache_hits:
        console.print(f"[dim]キャッシュから読み込んだページ: {cache_hits} 件[/dim]")
    path = out or (
        research_settings.output_dir
        / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{_slug(topic)}.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    console.print(f"保存しました: {path}")


class ConsoleObserver(DebateObserver):
    """ディベートの進行を Rich で表示する。"""

    def __init__(self) -> None:
        self._status: Status | None = None

    def close(self) -> None:
        self._stop_status()

    def _stop_status(self) -> None:
        if self._status is not None:
            self._status.stop()
            self._status = None

    def on_progress(self, message: str) -> None:
        if self._status is None:
            self._status = console.status(message)
            self._status.start()
        else:
            self._status.update(message)

    def on_statement_start(self, turn: Turn) -> None:
        self._stop_status()
        color = "cyan" if turn.side is Side.AFFIRMATIVE else "magenta"
        console.print(f"\n[bold {color}]【{turn.side.label}】[/bold {color}]")

    def on_token(self, turn: Turn, chunk: str) -> None:
        console.print(chunk, end="", markup=False, highlight=False, soft_wrap=True)

    def on_event(self, event: Event) -> None:
        match event:
            case EvidenceCollected():
                self._stop_status()
                console.rule("証拠品")
                for ev in event.report.evidence:
                    console.print(
                        f"[bold]{ev.id}[/bold] {escape(ev.title)} "
                        f"[dim](検証済みの事実 {len(ev.verified_facts)} 件)[/dim]"
                    )
            case PhaseStarted():
                self._stop_status()
                title = event.phase.label + (f" 第{event.round}回" if event.round else "")
                console.print()
                console.rule(f"[bold]{title}[/bold]")
            case StatementMade():
                cited = ", ".join(event.statement.cited_evidence_ids) or "なし"
                console.print(f"\n[dim]{event.statement.id} / 出典: {cited}[/dim]")
            case CitationIssuesDetected():
                for issue in event.issues:
                    console.print(f"[yellow]⚠ {escape(issue.detail)}[/yellow]")
            case ClaimsExtracted():
                console.print(f"[dim]主張 {len(event.claims)} 件を記録[/dim]")
            case JudgeScored():
                order = " → ".join(side.label for side in event.score.order)
                totals = " / ".join(f"{side.label} {event.score.total(side)} 点" for side in Side)
                console.print(f"[dim]評価(提示順 {order}): {totals}[/dim]")
            case VerdictDelivered():
                self._stop_status()
                v = event.verdict
                result = f"{v.winner.label}の勝ち" if v.winner else "引き分け"
                if not v.agreed:
                    result += "(順序を入れ替えた評価で判定が割れました)"
                console.print(
                    Panel(escape(v.rationale), title=f"判決: {result}", border_style="green")
                )
            case SessionAborted():
                self._stop_status()
                console.print(f"[red]中断: {escape(event.reason)}[/red]")
            case _:
                pass


def _fmt_s(ms: float | None) -> str:
    return "-" if ms is None else f"{ms / 1000:.1f}s"


def _summary_table(summary: DebateSummary) -> Table:
    table = Table(title="ターンごとの計測")
    for col in ("発言", "陣営", "フェーズ", "字数", "TTFT", "総時間", "出力トークン", "tok/s"):
        table.add_column(col, justify="right" if col not in ("陣営", "フェーズ") else "left")
    for t in summary.turns:
        table.add_row(
            t.statement_id,
            t.side.label,
            t.phase.label + (f" {t.round}" if t.round else ""),
            str(t.chars),
            _fmt_s(t.ttft_ms),
            _fmt_s(t.total_ms),
            str(t.output_tokens or "-"),
            _fmt_num(t.tokens_per_s),
        )
    return table


def _print_summary(summary: DebateSummary) -> None:
    console.print(_summary_table(summary))
    issues = ", ".join(f"{k} {v}" for k, v in summary.citation_issues.items()) or "なし"
    wall = f"{summary.wall_time_s:.0f}s" if summary.wall_time_s is not None else "-"
    console.print(
        f"LLM 呼び出し {summary.llm_calls} 回 / 入力 {summary.input_tokens} トークン・"
        f"出力 {summary.output_tokens} トークン / 全体 {wall}\n"
        f"構造化出力 {summary.structured_calls} 回(失敗 {summary.structured_failures}、"
        f"リトライ {summary.structured_retries})/ 主張 {summary.claims} 件 / 出典の問題: {issues}"
    )


@app.command()
def debate(
    topic: Annotated[str, typer.Argument(help="論題")],
    rounds: Annotated[int, typer.Option("--rounds", "-r", min=1, help="反論の往復数")] = 3,
    evidence: Annotated[
        Path | None,
        typer.Option("--evidence", "-e", help="既存の捜査結果 JSON(指定すると捜査を省略)"),
    ] = None,
) -> None:
    """LLM 同士でディベートを行い、判決まで進める。"""
    settings = Settings()
    recorder = BufferedRecorder()
    report = _load_report(evidence)
    try:
        client = LLMClient.from_settings(
            settings, backend_factory=backend_factory, recorder=recorder
        )
    except ConfigError as e:
        console.print(f"[red]設定エラー:[/red] {e}")
        raise typer.Exit(code=1) from e
    prompts = PromptLoader(settings.prompts_dir)
    observer = ConsoleObserver()

    async def run() -> tuple[list[Event], BaseException | None]:
        error: BaseException | None = None
        async with _engine_context(
            settings, client, recorder, prompts, observer, research=report is None
        ) as (engine, store):
            try:
                await engine.run(topic, rounds, evidence=report)
            except Exception as e:
                error = e
            events = await store.load(engine.session_id) if engine.session_id else []
        return events, error

    events, error = asyncio.run(run())
    _save_outputs(settings, events)
    _exit_on_error(error)


async def _ask(question: str, choices: list[str]) -> str:
    return await asyncio.to_thread(
        Prompt.ask, question, choices=choices, show_choices=False, console=console
    )


@app.command()
def play(
    topic: Annotated[str | None, typer.Argument(help="論題(--resume のときは不要)")] = None,
    side: Annotated[Side, typer.Option("--side", "-s", help="あなたが担当する陣営")] = (
        Side.NEGATIVE
    ),
    rounds: Annotated[int, typer.Option("--rounds", "-r", min=1, help="反論の往復数")] = 1,
    evidence: Annotated[
        Path | None,
        typer.Option("--evidence", "-e", help="既存の捜査結果 JSON(指定すると捜査を省略)"),
    ] = None,
    resume: Annotated[
        str | None, typer.Option("--resume", help="中断したセッションを再開する(セッション ID)")
    ] = None,
    reveal: Annotated[
        bool, typer.Option("--reveal", help="選ぶ前に候補の強さ(strong/weak/trap)を表示する")
    ] = False,
) -> None:
    """人間 vs LLM を CLI で遊ぶ(シナリオ検証用の簡易モード)。

    人間の手番で分析官の選択肢が表示されるので、番号で選ぶ。q で中断し、--resume で再開できる。
    """
    if resume is None and topic is None:
        console.print("[red]論題を指定するか、--resume でセッションを指定してください[/red]")
        raise typer.Exit(code=2)
    settings = Settings()
    recorder = BufferedRecorder()
    report = _load_report(evidence)
    try:
        client = LLMClient.from_settings(
            settings, backend_factory=backend_factory, recorder=recorder
        )
    except ConfigError as e:
        console.print(f"[red]設定エラー:[/red] {e}")
        raise typer.Exit(code=1) from e
    prompts = PromptLoader(settings.prompts_dir)
    observer = ConsoleObserver()

    async def run() -> tuple[list[Event], str, BaseException | None]:
        error: BaseException | None = None
        outcome = "finished"
        async with _engine_context(
            settings, client, recorder, prompts, observer, research=report is None
        ) as (engine, store):
            try:
                if resume is not None:
                    state = await engine.resume(resume)
                    if state.human_side is None:
                        raise SessionStateError("人間が参加していないセッションです")
                    console.print(f"再開: {escape(state.topic or '')}({state.human_side.label})")
                else:
                    assert topic is not None
                    await engine.start(topic, rounds, human_side=side)
                    await engine.collect_evidence(report)
                loop = PlayLoop(
                    engine, DEBATE_MODE, console, _ask, reveal=reveal, before_prompt=observer.close
                )
                outcome = await loop.run()
            except Exception as e:
                error = e
            events = await store.load(engine.session_id) if engine.session_id else []
        return events, outcome, error

    events, outcome, error = asyncio.run(run())
    if outcome == "quit" and events:
        session_id = events[0].session_id
        console.print(f"中断しました。再開するには: llm-court play --resume {session_id}")
        return
    _save_outputs(settings, events)
    _exit_on_error(error)


def _load_report(evidence: Path | None) -> ResearchReport | None:
    if evidence is None:
        return None
    try:
        return ResearchReport.model_validate_json(evidence.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        console.print(f"[red]捜査結果を読み込めません:[/red] {e}")
        raise typer.Exit(code=1) from e


@asynccontextmanager
async def _engine_context(
    settings: Settings,
    client: LLMClient,
    recorder: BufferedRecorder,
    prompts: PromptLoader,
    observer: "ConsoleObserver",
    *,
    research: bool,
) -> AsyncGenerator[tuple[DebateEngine, EventStore]]:
    """CLI 用にイベントストア・LLM・(必要なら)捜査パイプラインをつないだエンジンを用意する。"""
    store = await EventStore.open(settings.database_path)
    try:
        async with client, http_client_factory() as http:
            pipeline = research_pipeline(settings, client, prompts, http)
            yield (
                DebateEngine(
                    llm=client,
                    recorder=recorder,
                    prompts=prompts,
                    store=store,
                    mode=DEBATE_MODE,
                    research=pipeline.run if research else None,
                    observer=observer,
                ),
                store,
            )
    finally:
        observer.close()
        await store.aclose()


def research_pipeline(
    settings: Settings, client: LLMClient, prompts: PromptLoader, http: httpx.AsyncClient
) -> ResearchPipeline:
    research_settings = settings.research
    return ResearchPipeline(
        client,
        prompts,
        SearXNGClient(
            settings.searxng_url, timeout_s=research_settings.fetch_timeout_s, client=http
        ),
        PageFetcher(research_settings, client=http, cache=PageCache(research_settings.cache_dir)),
        research_settings,
    )


def _save_outputs(settings: Settings, events: list[Event]) -> None:
    """イベントログ(JSONL)と法廷記録(Markdown)を保存し、計測サマリを表示する。"""
    if not events:
        return
    state = DebateState.from_events(events)
    out_dir = settings.debate_output_dir
    jsonl = out_dir / f"{state.session_id}.jsonl"
    markdown = out_dir / f"{state.session_id}.md"
    export_jsonl(events, jsonl)
    markdown.write_text(render_markdown(state, DEBATE_MODE), encoding="utf-8")
    console.print()
    _print_summary(summarize(events))
    console.print(f"保存しました: {jsonl} / {markdown}")


def _exit_on_error(error: BaseException | None) -> None:
    if error is None:
        return
    label = "接続エラー" if isinstance(error, SearchError | LLMConnectionError) else "エラー"
    console.print(f"[red]{label}:[/red] {escape(str(error))}")
    raise typer.Exit(code=1)


def _metrics_table(metrics: list[ConfigMetrics]) -> Table:
    table = Table(title="構成の比較")
    table.add_column("指標")
    for m in metrics:
        table.add_column(m.config, justify="right")

    def pct(v: float | None) -> str:
        return "-" if v is None else f"{v:.0%}"

    def sec(v: float | None) -> str:
        return "-" if v is None else f"{v:.1f}s"

    rows: list[tuple[str, list[str]]] = [
        ("完了 / 中断", [f"{m.completed} / {m.aborted}" for m in metrics]),
        ("順序反転率 ↓", [pct(m.order_flip_rate) for m in metrics]),
        ("再評価の安定性 ↑", [pct(m.repeat_stability) for m in metrics]),
        ("存在しない証拠品の率 ↓", [pct(m.unknown_evidence_rate) for m in metrics]),
        ("証拠品にない引用の率 ↓", [pct(m.unsupported_quote_rate) for m in metrics]),
        ("構造化出力の失敗率 ↓", [pct(m.structured_failure_rate) for m in metrics]),
        ("発言の総時間 p50 / p90", [f"{sec(m.turn_p50_s)} / {sec(m.turn_p90_s)}" for m in metrics]),
        ("TTFT p50", [sec(m.ttft_p50_s) for m in metrics]),
    ]
    for label, values in rows:
        table.add_row(label, *values)
    return table


@app.command("eval")
def eval_command(
    spec_path: Annotated[Path, typer.Argument(help="評価仕様ファイル(YAML)")],
    out: Annotated[
        Path | None, typer.Option("--out", "-o", help="結果の保存先(既定は eval_output_dir)")
    ] = None,
) -> None:
    """同じテーマ群で複数のモデル構成のディベートを回し、指標を比較したレポートを作る。"""
    settings = Settings()
    try:
        spec = load_spec(spec_path)
    except EvalSpecError as e:
        console.print(f"[red]評価仕様のエラー:[/red] {escape(str(e))}")
        raise typer.Exit(code=1) from e
    prompts = PromptLoader(settings.prompts_dir)
    out_dir = out or (
        settings.eval_output_dir / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{_slug(spec.name)}"
    )

    def client_factory(models: ModelsConfig, recorder: BufferedRecorder) -> LLMClient:
        return LLMClient(
            models,
            prompts=prompts,
            structured_max_retries=settings.llm_structured_max_retries,
            backend_factory=backend_factory,
            recorder=recorder,
        )

    harness = EvalHarness(
        prompts=prompts, mode=DEBATE_MODE, client_factory=client_factory, out_dir=out_dir
    )

    async def run() -> EvalResult:
        with console.status("評価を実行中…") as status:
            return await harness.run(spec, on_progress=lambda m: status.update(m))

    try:
        result = asyncio.run(run())
    except (ConfigError, LLMConnectionError) as e:
        console.print(f"[red]エラー:[/red] {escape(str(e))}")
        raise typer.Exit(code=1) from e

    _report(result, out_dir)


def _report(result: EvalResult, out_dir: Path) -> None:
    metrics = compute_metrics(result, DEBATE_MODE)
    files = write_report(result, metrics, out_dir)
    console.print(_metrics_table(metrics))
    console.print(f"レポート: {files.markdown}")
    console.print(
        f"[dim]CSV: {files.runs_csv.name}, {files.turns_csv.name}, {files.summary_csv.name}[/dim]"
    )


@app.command("eval-report")
def eval_report(
    out_dir: Annotated[Path, typer.Argument(help="llm-court eval の結果ディレクトリ")],
) -> None:
    """保存済みの評価結果から指標を計算し直し、レポートを作り直す(ディベートは再実行しない)。"""
    try:
        result = load_result(out_dir)
    except (OSError, ValueError) as e:
        console.print(f"[red]評価結果を読み込めません:[/red] {escape(str(e))}")
        raise typer.Exit(code=1) from e
    _report(result, out_dir)


@app.command()
def serve(
    host: Annotated[str, typer.Option(help="待ち受けるアドレス")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="待ち受けるポート")] = 8000,
) -> None:
    """API サーバー(REST + SSE)を起動する。"""
    import uvicorn

    from llm_court.api import create_app

    settings = Settings()
    api = create_app(
        settings, backend_factory=backend_factory, http_client_factory=http_client_factory
    )
    uvicorn.run(api, host=host, port=port, log_level=settings.log_level.lower())


@app.command()
def openapi(
    out: Annotated[
        Path | None, typer.Option("--out", "-o", help="出力先(省略すると標準出力)")
    ] = None,
) -> None:
    """API の OpenAPI スキーマ(JSON)を出力する(フロントエンドの型生成用)。"""
    import json

    from llm_court.api import create_app

    schema = json.dumps(create_app(Settings()).openapi(), ensure_ascii=False, indent=2)
    if out is None:
        typer.echo(schema)
    else:
        out.write_text(schema + "\n", encoding="utf-8")
        console.print(f"保存しました: {out}")


if __name__ == "__main__":
    app()
