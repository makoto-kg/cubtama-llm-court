"""裁判型の事件の生成・検証・一覧(`llm-court case ...`)。"""

import asyncio
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from llm_court.config import ConfigError, Settings
from llm_court.domain import Case, ResearchReport
from llm_court.llm import InMemoryRecorder, LLMClient, LLMError, PromptLoader
from llm_court.modes import TRIAL_MODE
from llm_court.scenario.generator import CaseGenerationError, CaseGenerator
from llm_court.scenario.store import CaseNotFoundError, CaseStore

case_app = typer.Typer(help="裁判型の事件(生成・検証・一覧)。", no_args_is_help=True)
console = Console()


def _load_evidence(path: Path | None) -> ResearchReport | None:
    if path is None:
        return None
    try:
        return ResearchReport.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        console.print(f"[red]捜査結果を読み込めません:[/red] {e}")
        raise typer.Exit(code=1) from e


def _client(settings: Settings, recorder: InMemoryRecorder) -> LLMClient:
    from llm_court.cli import main as cli  # 実行時に読む(テストでの差し替えと循環 import の回避)

    try:
        return LLMClient.from_settings(
            settings, backend_factory=cli.backend_factory, recorder=recorder
        )
    except ConfigError as e:
        console.print(f"[red]設定エラー:[/red] {e}")
        raise typer.Exit(code=1) from e


def print_case(case: Case) -> None:
    console.rule(f"[bold]{escape(case.title)}[/bold]({case.id})")
    console.print(escape(case.overview))
    console.print(f"\n[bold]問い[/bold] {escape(case.question.text)}")
    for i, option in enumerate(case.question.options):
        mark = "[green](正解)[/green]" if i == case.question.answer_index else ""
        console.print(f"  {i}. {escape(option)} {mark}")

    console.print("\n[bold]学習ポイント[/bold]")
    for lp in case.learning_points:
        outdated = (
            f" [yellow]古い知識: {escape(lp.outdated_belief or '')}[/yellow]" if lp.outdated else ""
        )
        console.print(f"  {lp.id} {escape(lp.knowledge)}{outdated}")
        sources = ", ".join(s.evidence_id for s in lp.sources)
        console.print(f"    [dim]誤解: {escape(lp.misconception)} / 出典: {sources}[/dim]")

    table = Table(title="矛盾(正解)と罠", show_lines=True)
    table.add_column("ID")
    table.add_column("証言")
    table.add_column("つきつける証拠品")
    table.add_column("知識")
    table.add_column("罠")
    lines = case.testimony_lines
    evidence = {e.id: e.name for e in case.evidence}
    for c in case.contradictions:
        table.add_row(
            c.id,
            escape(lines[c.testimony_line_id].text),
            escape(f"{c.evidence_id} {evidence.get(c.evidence_id, '')}"),
            ", ".join(c.learning_point_ids),
            escape("\n".join(f"{t.evidence_id}: {t.why_tempting}" for t in c.traps)),
        )
    console.print(table)
    console.print(
        f"人物 {len(case.people)} / 時系列 {len(case.hidden_truth.timeline)}"
        f" / 証拠品 {len(case.evidence)} / 証言 {len(case.testimonies)}"
    )
    print_validation(case)


def print_validation(case: Case) -> None:
    v = case.validation
    if v is None:
        console.print("[yellow]未検証[/yellow]")
        return
    for issue in v.issues:
        console.print(
            f"[red]✗ {escape(issue.message)}[/red]([dim]{issue.code} → {issue.step}[/dim])"
        )
    for n, run in enumerate(v.solver_runs, start=1):
        console.print(
            f"solver {n}: 矛盾 {len(run.found)}/{len(case.contradictions)} / "
            f"手数 {run.steps if run.steps is not None else '-'} / 余分な指摘 {run.extra} / "
            f"問い {'正解' if run.answer_correct else '不正解'}"
        )
    status = "[green]解ける[/green]" if v.solved else "[red]解けない[/red]"
    unique = "一意" if v.unique else "一意でない可能性"
    steps = f" / 最短 {v.min_steps} 手" if v.min_steps is not None else ""
    attempted = v.attempted_runs or len(v.solver_runs)
    solved_runs = sum(r.solved for r in v.solver_runs)
    rate = ""
    if attempted:
        rate = f" / 解答率 {v.solve_rate:.0%}({attempted} 回中 {solved_runs} 回"
        rate += f"、基準 {v.min_solve_rate:.0%})"
        rate += f" / 全矛盾の発見 {v.detect_rate:.0%} / 問いの正答 {v.answer_rate:.0%}"
    console.print(f"検証: {status} / {unique}{steps}{rate}")
    g = case.generation
    if g is not None:
        console.print(
            f"[dim]LLM 呼び出し {g.llm_calls} 回 / 出力 {g.output_tokens} tok / "
            f"{g.llm_time_s:.0f}s / 作り直し {g.regenerations or 'なし'}[/dim]"
        )


@case_app.command("generate")
def generate(
    theme: Annotated[str, typer.Argument(help="テーマ")],
    evidence: Annotated[
        Path | None,
        typer.Option("--evidence", "-e", help="既存の捜査結果 JSON(指定すると捜査を省略)"),
    ] = None,
) -> None:
    """テーマから事件を段階的に生成し、整合性チェックと solver で検証して保存する。"""
    from llm_court.cli import main as cli

    settings = Settings()
    report = _load_evidence(evidence)
    recorder = InMemoryRecorder()
    client = _client(settings, recorder)
    prompts = PromptLoader(settings.prompts_dir)

    async def run() -> Case:
        async with client, cli.http_client_factory() as http:
            pipeline = cli.research_pipeline(settings, client, prompts, http)
            generator = CaseGenerator(
                llm=client,
                recorder=recorder,
                prompts=prompts,
                mode=TRIAL_MODE,
                settings=settings.scenario,
                research=pipeline.run,
            )
            with console.status("事件を生成しています…") as status:
                return await generator.generate(
                    theme, evidence=report, on_progress=lambda m: status.update(m)
                )

    try:
        case = asyncio.run(run())
    except (CaseGenerationError, LLMError) as e:
        console.print(f"[red]事件を生成できませんでした:[/red] {escape(str(e))}")
        raise typer.Exit(code=1) from e
    path = CaseStore(settings.scenario.case_dir).save(case)
    print_case(case)
    console.print(f"保存しました: {path}")
    if not (case.validation and case.validation.solved):
        console.print("[red]solver が解ける事件になりませんでした(保存はしています)[/red]")
        raise typer.Exit(code=1)


@case_app.command("validate")
def validate(
    case_id: Annotated[str, typer.Argument(help="事件の ID")],
    runs: Annotated[
        int | None, typer.Option("--runs", "-n", min=1, help="solver に解かせる回数(既定は設定値)")
    ] = None,
) -> None:
    """保存済みの事件を、整合性チェックと solver で検証し直して結果を更新する。"""
    settings = Settings()
    store = CaseStore(settings.scenario.case_dir)
    try:
        case = store.load(case_id)
    except CaseNotFoundError as e:
        console.print(f"[red]事件 {case_id} はありません[/red]")
        raise typer.Exit(code=1) from e
    recorder = InMemoryRecorder()
    client = _client(settings, recorder)
    prompts = PromptLoader(settings.prompts_dir)

    async def run() -> Case:
        async with client:
            generator = CaseGenerator(
                llm=client,
                recorder=recorder,
                prompts=prompts,
                mode=TRIAL_MODE,
                settings=settings.scenario,
            )
            with console.status("検証しています…"):
                return await generator.validate(case, runs)

    try:
        validated = asyncio.run(run())
    except LLMError as e:
        console.print(f"[red]検証できませんでした:[/red] {escape(str(e))}")
        raise typer.Exit(code=1) from e
    store.save(validated)
    print_validation(validated)
    if not (validated.validation and validated.validation.solved):
        raise typer.Exit(code=1)


@case_app.command("list")
def list_cases() -> None:
    """保存済みの事件の一覧。"""
    settings = Settings()
    cases = CaseStore(settings.scenario.case_dir).list()
    if not cases:
        console.print("事件はまだありません")
        return
    table = Table(title="事件")
    for column in ("ID", "タイトル", "テーマ", "矛盾", "検証", "作成"):
        table.add_column(column)
    for c in cases:
        v = c.validation
        status = "未検証" if v is None else ("解ける" if v.solved else "解けない")
        table.add_row(
            c.id,
            escape(c.title),
            escape(c.theme),
            str(len(c.contradictions)),
            status,
            c.created_at.strftime("%Y-%m-%d %H:%M"),
        )
    console.print(table)
