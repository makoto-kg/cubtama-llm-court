"""裁判型を CLI で遊ぶ(`llm-court trial`)と、証人の逸脱率の評価(`llm-court eval-trial`)。

どちらもシナリオ検証用の簡易モード。エンジンを直接動かす。
"""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal

import typer
from rich.console import Console
from rich.markup import escape
from rich.prompt import Prompt
from rich.status import Status
from rich.table import Table

from llm_court.cli.play import AskFn, gauge_bar
from llm_court.config import ConfigError, Settings
from llm_court.domain import (
    Case,
    ContradictionSolved,
    Event,
    TestimonyStarted,
    TrialOption,
    WitnessResponded,
)
from llm_court.engine.explanation import build_explanation
from llm_court.engine.recorder import BufferedRecorder
from llm_court.engine.store import EventStore, export_jsonl
from llm_court.engine.trial import TrialEngine, TrialObserver
from llm_court.engine.trial_state import TrialState
from llm_court.eval.trial_eval import (
    ResponseRow,
    play_scripted,
    response_rows,
    summarize_rows,
    write_trial_report,
)
from llm_court.llm import LLMClient, LLMConnectionError, PromptLoader
from llm_court.modes import TRIAL_MODE, TrialMode
from llm_court.scenario.store import CaseNotFoundError, CaseStore

console = Console()
QUIT = "q"
_STRENGTH_STYLES = {"strong": "green", "weak": "yellow", "trap": "red"}


async def _ask(question: str, choices: list[str]) -> str:
    return await asyncio.to_thread(
        Prompt.ask, question, choices=choices, show_choices=False, console=console
    )


def _strength(option: TrialOption) -> str:
    if option.strength is None:
        return "-"
    style = _STRENGTH_STYLES[option.strength]
    return f"[{style}]{option.strength}[/{style}]"


class TrialConsoleObserver(TrialObserver):
    """証人の応答をストリーミング表示する。"""

    def __init__(self, case: Case | None = None, *, quiet: bool = False) -> None:
        self._names = {p.id: p.name for p in case.people} if case else {}
        self._quiet = quiet
        self._status: Status | None = None

    def set_case(self, case: Case) -> None:
        self._names = {p.id: p.name for p in case.people}

    def close(self) -> None:
        if self._status is not None:
            self._status.stop()
            self._status = None

    def on_progress(self, message: str) -> None:
        if self._quiet:
            return
        if self._status is None:
            self._status = console.status(message)
            self._status.start()
        else:
            self._status.update(message)

    def on_witness_start(self, witness_id: str) -> None:
        self.close()
        if not self._quiet:
            name = self._names.get(witness_id, witness_id)
            console.print(f"\n[bold magenta]【{escape(name)}】[/bold magenta]")

    def on_witness_token(self, witness_id: str, chunk: str) -> None:
        if not self._quiet:
            console.print(chunk, end="", markup=False, highlight=False, soft_wrap=True)

    def on_event(self, event: Event) -> None:
        if self._quiet:
            return
        match event:
            case WitnessResponded():
                self.close()
                console.print()
            case ContradictionSolved():
                console.print("[bold green]反証成功! 証言が崩れた[/bold green]")
            case TestimonyStarted():
                console.print()
            case _:
                pass


class TrialLoop:
    """選択肢を選ばせ、証人の応答を見せることを閉廷まで繰り返す。"""

    def __init__(
        self,
        engine: TrialEngine,
        mode: TrialMode,
        ask: AskFn,
        *,
        reveal: bool = False,
        observer: TrialConsoleObserver | None = None,
    ) -> None:
        self._engine = engine
        self._mode = mode
        self._ask = ask
        self._reveal = reveal
        self._observer = observer

    async def run(self) -> Literal["finished", "quit"]:
        while True:
            state = self._engine.state
            if self._observer is not None:
                self._observer.close()
            match state.stage:
                case "finished":
                    self._show_result(state)
                    return "finished"
                case "examining":
                    await self._engine.advance()
                case "answering":
                    if await self._answer(state) == QUIT:
                        return "quit"
                case "choosing":
                    if await self._choose(state) == QUIT:
                        return "quit"
                case "responding":
                    # 応答の途中で中断したセッションは再開できない
                    console.print("[red]証人の応答の途中で止まっています[/red]")
                    return "quit"

    async def _choose(self, state: TrialState) -> str:
        pending = state.pending_choices
        testimony = state.testimony
        case = state.case
        assert pending is not None and testimony is not None and case is not None
        names = {p.id: p.name for p in case.people}
        solved_lines = {c.testimony_line_id for c in case.contradictions if c.id in state.solved}
        console.print()
        console.rule(
            f"[bold]{escape(testimony.title)}[/bold](証人: {escape(names[testimony.witness_id])})"
        )
        for line in testimony.lines:
            mark = "[green]✓[/green]" if line.id in solved_lines else " "
            console.print(f" {mark} {escape(line.text)}")
        console.print(
            f"ペナルティゲージ: {gauge_bar(state.penalty_gauge, self._mode.penalty_gauge)}"
        )
        table = Table(show_lines=False)
        table.add_column("番号", justify="right", no_wrap=True)
        table.add_column("選択肢", overflow="fold")
        if self._reveal:
            table.add_column("強さ", no_wrap=True)
        for i, option in enumerate(pending.options, start=1):
            row = [str(i), escape(option.label)]
            if self._reveal:
                row.append(_strength(option))
            table.add_row(*row)
        console.print(table)
        answers = [str(i) for i in range(1, len(pending.options) + 1)]
        answer = await self._ask(
            "番号を選んでください(e で証拠品、q で中断)", [*answers, "e", QUIT]
        )
        if answer == "e":
            _print_evidence(case)
            return answer
        if answer == QUIT:
            return answer
        option = pending.options[int(answer) - 1]
        before = len(self._engine.state.responses)
        await self._engine.choose(option.id)
        self._show_outcome(before)
        return answer

    def _show_outcome(self, responses_before: int) -> None:
        state = self._engine.state
        made = state.choices[-1].option
        if made.strength is not None and made.strength != "strong":
            console.print(f"つきつけた組: {_strength(made)}")
            if made.trap_reason:
                console.print(f"[dim]罠: {escape(made.trap_reason)}[/dim]")
        lost = self._mode.penalty_for(made.strength)
        if lost:
            bar = gauge_bar(state.penalty_gauge, self._mode.penalty_gauge)
            console.print(f"[red]ペナルティ −{lost}[/red] ゲージ: {bar}")
        if self._reveal and len(state.responses) > responses_before:
            check = state.responses[-1].check
            if check is not None:
                verdict = ", ".join(check.deviations) or "逸脱なし"
                console.print(f"[dim]台本の判定: {verdict} — {escape(check.reason)}[/dim]")

    async def _answer(self, state: TrialState) -> str:
        case = state.case
        assert case is not None
        console.print()
        console.rule("[bold]すべての矛盾を解きました[/bold]")
        console.print(f"[bold]問い[/bold] {escape(case.question.text)}")
        for i, option in enumerate(case.question.options, start=1):
            console.print(f"  {i}. {escape(option)}")
        answers = [str(i) for i in range(1, len(case.question.options) + 1)]
        answer = await self._ask("答えを選んでください(q で中断)", [*answers, QUIT])
        if answer != QUIT:
            await self._engine.answer(int(answer) - 1)
        return answer

    def _show_result(self, state: TrialState) -> None:
        if state.aborted is not None:
            console.print(f"[red]中断: {escape(state.aborted)}[/red]")
            return
        case = state.case
        assert case is not None
        labels = {
            "solved": "[green]事件を解決しました[/green]",
            "wrong_answer": "[yellow]矛盾はすべて解きましたが、問いの答えが違いました[/yellow]",
            "penalty": "[red]ペナルティゲージが尽きました[/red]",
        }
        console.print()
        console.rule("閉廷")
        console.print(labels[state.result or "penalty"])
        print_explanation(case)


def _print_evidence(case: Case) -> None:
    console.rule("証拠品")
    for e in case.evidence:
        console.print(f"[bold]{escape(e.name)}[/bold]: {escape(e.description)}")
        for d in e.details:
            console.print(f"  - {escape(d)}")


def print_explanation(case: Case) -> None:
    explanation = build_explanation(case)
    console.rule("解説")
    console.print(f"[bold]真相[/bold] {escape(explanation.truth)}")
    console.print(f"[bold]問いの答え[/bold] {escape(explanation.answer)}")
    lps = {lp.id: lp for lp in explanation.learning_points}
    for item in explanation.items:
        console.print()
        console.print(
            f"[bold]{item.contradiction_id}[/bold] {escape(item.witness_name)}"
            f"「{escape(item.testimony_line)}」× {escape(item.evidence_name)}"
        )
        console.print(f"  {escape(item.explanation)}")
        for lp_id in item.learning_point_ids:
            lp = lps.get(lp_id)
            if lp is None:
                continue
            console.print(f"  [cyan]知識[/cyan] {escape(lp.knowledge)}")
            if lp.outdated and lp.outdated_belief:
                console.print(f"    [yellow]以前の通説: {escape(lp.outdated_belief)}[/yellow]")
            for s in lp.sources:
                console.print(
                    f"    [dim]出典: {escape(s.title)} {s.url}「{escape(s.quote)}」[/dim]"
                )
        for trap in item.traps:
            console.print(
                f"  [red]罠[/red] {escape(trap.evidence_name)}: {escape(trap.why_tempting)}"
            )


def _client(settings: Settings, recorder: BufferedRecorder) -> LLMClient:
    from llm_court.cli import main as cli  # 実行時に読む(テストでの差し替えと循環 import の回避)

    try:
        return LLMClient.from_settings(
            settings, backend_factory=cli.backend_factory, recorder=recorder
        )
    except ConfigError as e:
        console.print(f"[red]設定エラー:[/red] {e}")
        raise typer.Exit(code=1) from e


def _load_case(settings: Settings, case_id: str) -> Case:
    try:
        return CaseStore(settings.scenario.case_dir).load(case_id)
    except CaseNotFoundError as e:
        console.print(f"[red]事件 {case_id} はありません[/red]")
        raise typer.Exit(code=1) from e


@asynccontextmanager
async def _engine(
    settings: Settings,
    client: LLMClient,
    recorder: BufferedRecorder,
    mode: TrialMode,
    observer: TrialObserver,
    db: Path | None,
) -> AsyncGenerator[tuple[TrialEngine, EventStore]]:
    store = await EventStore.open(db)
    try:
        async with client:
            yield (
                TrialEngine(
                    llm=client,
                    recorder=recorder,
                    prompts=PromptLoader(settings.prompts_dir),
                    store=store,
                    mode=mode,
                    observer=observer,
                ),
                store,
            )
    finally:
        await store.aclose()


def trial(
    case_id: Annotated[str | None, typer.Argument(help="事件の ID(--resume のときは不要)")] = None,
    resume: Annotated[
        str | None, typer.Option("--resume", help="中断した裁判を再開する(セッション ID)")
    ] = None,
    reveal: Annotated[
        bool,
        typer.Option("--reveal", help="選ぶ前に選択肢の強さを、応答後に台本の判定を表示する"),
    ] = False,
) -> None:
    """裁判型の事件を CLI で遊ぶ(シナリオ検証用の簡易モード)。

    証言ごとに選択肢(つきつける / ゆさぶる)が表示されるので、番号で選ぶ。
    全矛盾を解いたら最後の問いに答え、閉廷後に解説を表示する。q で中断し、--resume で再開できる。
    """
    if resume is None and case_id is None:
        console.print("[red]事件の ID を指定するか、--resume で裁判を指定してください[/red]")
        raise typer.Exit(code=2)
    settings = Settings()
    case = _load_case(settings, case_id) if case_id is not None else None
    recorder = BufferedRecorder()
    client = _client(settings, recorder)
    observer = TrialConsoleObserver(case)

    async def run() -> tuple[list[Event], str, BaseException | None]:
        error: BaseException | None = None
        outcome = "finished"
        async with _engine(
            settings, client, recorder, TRIAL_MODE, observer, settings.database_path
        ) as (engine, store):
            try:
                if resume is not None:
                    state = await engine.resume(resume)
                    assert state.case is not None
                    observer.set_case(state.case)
                    console.print(f"再開: {escape(state.case.title)}")
                else:
                    assert case is not None
                    console.rule(f"[bold]{escape(case.title)}[/bold]")
                    console.print(escape(case.overview))
                    console.print(
                        "登場人物: "
                        + "、".join(f"{escape(p.name)}({escape(p.role)})" for p in case.people)
                    )
                    _print_evidence(case)
                    await engine.start(case)
                loop = TrialLoop(engine, TRIAL_MODE, _ask, reveal=reveal, observer=observer)
                outcome = await loop.run()
            except Exception as e:
                error = e
            finally:
                observer.close()
            events = await store.load(engine.session_id) if engine.session_id else []
        return events, outcome, error

    events, outcome, error = asyncio.run(run())
    if outcome == "quit" and events:
        console.print(
            f"中断しました。再開するには: llm-court trial --resume {events[0].session_id}"
        )
        return
    if events:
        path = settings.debate_output_dir / f"trial-{events[0].session_id}.jsonl"
        export_jsonl(events, path)
        console.print(f"保存しました: {path}")
    if error is not None:
        label = "接続エラー" if isinstance(error, LLMConnectionError) else "エラー"
        console.print(f"[red]{label}:[/red] {escape(str(error))}")
        raise typer.Exit(code=1)


def eval_trial(
    case_ids: Annotated[list[str], typer.Argument(help="評価に使う事件の ID(複数可)")],
    runs: Annotated[int, typer.Option("--runs", "-n", min=1, help="事件ごとの実行回数")] = 1,
    out: Annotated[
        Path | None, typer.Option("--out", "-o", help="結果の保存先(既定は eval_output_dir)")
    ] = None,
) -> None:
    """自動プレイヤーで事件を遊び、証人の台本逸脱率(自白の早すぎ・崩れ損ね・漏洩)を測る。"""
    settings = Settings()
    cases = [_load_case(settings, cid) for cid in case_ids]
    out_dir = out or settings.eval_output_dir / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-trial"
    recorder = BufferedRecorder()
    client = _client(settings, recorder)
    # はずれ・罠を選んでもゲージが尽きないようにする(逸脱を測るのが目的)
    mode = TRIAL_MODE.model_copy(update={"penalty_gauge": 1000, "check_deviations": True})
    observer = TrialConsoleObserver(quiet=True)

    async def run() -> tuple[list[ResponseRow], dict[str, str], list[str]]:
        rows: list[ResponseRow] = []
        failures: list[str] = []
        models: dict[str, str] = {}
        out_dir.mkdir(parents=True, exist_ok=True)
        async with _engine(settings, client, recorder, mode, observer, out_dir / "events.db") as (
            engine,
            store,
        ):
            with console.status("評価を実行中…") as status:
                for case in cases:
                    for n in range(1, runs + 1):
                        status.update(f"{case.id} の {n}/{runs} 回目を遊んでいます")
                        try:
                            state = await play_scripted(engine, case)
                        except LLMConnectionError:
                            raise
                        except Exception:  # 1 回の失敗で評価全体を止めない(中断は記録済み)
                            state = engine.state
                        if state.result is None:
                            reason = state.aborted or f"閉廷しませんでした({state.stage})"
                            failures.append(f"{case.id} #{n}: {reason}")
                        models = state.models or models
                        events = await store.load(engine.session_id)
                        export_jsonl(events, out_dir / f"{case.id}-{n}.jsonl")
                        rows += response_rows(case.id, n, events)
        return rows, models, failures

    try:
        rows, models, failures = asyncio.run(run())
    except LLMConnectionError as e:
        console.print(f"[red]接続エラー:[/red] {escape(str(e))}")
        raise typer.Exit(code=1) from e
    metrics = summarize_rows(rows)
    path = write_trial_report(out_dir, rows, metrics, models=models, failures=failures)

    def pct(v: float | None) -> str:
        return "-" if v is None else f"{v:.0%}"

    table = Table(title="証人の台本逸脱率")
    for column in ("範囲", "応答", "自白の早すぎ ↓", "崩れ損ね ↓", "漏洩 ↓", "逸脱(全体)↓"):
        table.add_column(column)
    for m in metrics:
        table.add_row(
            m.scope,
            f"{m.checked}/{m.responses}",
            pct(m.premature_confession_rate),
            pct(m.failed_collapse_rate),
            pct(m.leak_rate),
            pct(m.deviation_rate),
        )
    console.print(table)
    for f in failures:
        console.print(f"[red]完走できませんでした:[/red] {escape(f)}")
    console.print(f"レポート: {path}")
