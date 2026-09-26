"""CLI で遊ぶ人間 vs LLM(シナリオ検証用の簡易モード)。

エンジンを直接動かし、人間の手番で選択肢を表示して番号で選ばせる。
"""

from collections.abc import Awaitable, Callable
from typing import Literal

from rich.console import Console
from rich.markup import escape
from rich.table import Table

from llm_court.domain import ChoiceOption, ChoicesPrepared
from llm_court.engine.debate import DebateEngine
from llm_court.engine.state import DebateState
from llm_court.modes import DebateMode

AskFn = Callable[[str, list[str]], Awaitable[str]]
"""(質問文, 受け付ける答え) → 入力された答え。"""

QUIT = "q"

_KIND_LABELS = {"contradiction": "つきつける", "probe": "ゆさぶる", "argument": "方針"}
_STRENGTH_STYLES = {"strong": "green", "weak": "yellow", "trap": "red"}


def _strength(option: ChoiceOption) -> str:
    strength = option.strength
    if strength is None:
        return "-"
    style = _STRENGTH_STYLES[strength]
    return f"[{style}]{strength}[/{style}]"


def gauge_bar(remaining: int, maximum: int) -> str:
    remaining = max(remaining, 0)
    return "■" * remaining + "□" * max(maximum - remaining, 0) + f" {remaining}/{maximum}"


class PlayLoop:
    """人間の手番まで進め、選択肢を選ばせることを判決まで繰り返す。"""

    def __init__(
        self,
        engine: DebateEngine,
        mode: DebateMode,
        console: Console,
        ask: AskFn,
        *,
        reveal: bool = False,
        before_prompt: Callable[[], None] | None = None,
    ) -> None:
        self._engine = engine
        self._mode = mode
        self._console = console
        self._ask = ask
        self._reveal = reveal
        self._before_prompt = before_prompt or (lambda: None)

    async def run(self) -> Literal["finished", "quit"]:
        while True:
            state = await self._engine.run_to_end()
            if state.finished:
                self._show_result(state)
                return "finished"
            pending = state.pending_choices
            assert pending is not None  # 判決前に run_to_end が止まるのは人間の手番だけ
            self._before_prompt()
            self._show_choices(pending, state)
            answers = [str(i) for i in range(1, len(pending.options) + 1)]
            answer = await self._ask("番号を選んでください(q で中断)", [*answers, QUIT])
            if answer == QUIT:
                return "quit"
            option = pending.options[int(answer) - 1]
            gauge_before = state.penalty_gauge
            await self._engine.choose(option.id)
            self._show_outcome(option, gauge_before)

    def _show_choices(self, pending: ChoicesPrepared, state: DebateState) -> None:
        console = self._console
        title = pending.phase.label + (f" 第{pending.round}回" if pending.round else "")
        console.print()
        console.rule(f"[bold]あなたの番({pending.side.label} / {title})[/bold]")
        console.print(
            f"ペナルティゲージ: {gauge_bar(state.penalty_gauge, self._mode.penalty_gauge)}"
        )
        table = Table(show_lines=True)
        # 検証用なので、選択肢・判断理由は省略せずに折り返して全文を表示する
        table.add_column("番号", justify="right", no_wrap=True)
        table.add_column("種類", no_wrap=True)
        table.add_column("選択肢", overflow="fold", ratio=3)
        if self._reveal:
            table.add_column("強さ", no_wrap=True)
            table.add_column("判断理由", overflow="fold", ratio=2)
        for i, option in enumerate(pending.options, start=1):
            row = [
                str(i),
                _KIND_LABELS.get(option.kind, option.kind),
                f"[bold]{escape(option.label)}[/bold]\n{escape(option.pitch)}",
            ]
            if self._reveal:
                rationale = option.contradiction.rationale if option.contradiction else None
                row += [_strength(option), escape(rationale or "-")]
            table.add_row(*row)
        console.print(table)
        if pending.discarded:
            console.print(f"[dim](参照が不正で除外した候補: {pending.discarded} 件)[/dim]")

    def _show_outcome(self, chosen: ChoiceOption, gauge_before: int) -> None:
        state = self._engine.state
        made = state.choices[-1].option if state.choices else chosen
        if made.strength is not None:
            rationale = made.contradiction.rationale if made.contradiction else None
            self._console.print(
                f"選んだ指摘の強さ: {_strength(made)}"
                + (f" — {escape(rationale)}" if rationale else "")
            )
        lost = gauge_before - state.penalty_gauge
        if lost > 0:
            bar = gauge_bar(state.penalty_gauge, self._mode.penalty_gauge)
            self._console.print(f"[red]ペナルティ −{lost}[/red] ゲージ: {bar}")

    def _show_result(self, state: DebateState) -> None:
        console = self._console
        if state.aborted is not None:
            console.print(f"[red]中断: {escape(state.aborted)}[/red]")
            return
        console.rule("あなたの選択")
        for made in state.choices:
            option = made.option
            strength = f" {_strength(option)}" if option.strength else ""
            console.print(f"- {escape(option.label)}{strength}")
        console.print(f"最終ゲージ: {gauge_bar(state.penalty_gauge, self._mode.penalty_gauge)}")
        verdict = state.verdict
        if verdict is not None and state.human_side is not None:
            if verdict.winner is None:
                result = "引き分け"
            elif verdict.winner is state.human_side:
                result = "[green]あなたの勝ち[/green]"
            else:
                result = "[red]あなたの負け[/red]"
            reason = "(ペナルティゲージが尽きた)" if verdict.decided_by == "penalty" else ""
            console.print(f"結果: {result}{reason}")
