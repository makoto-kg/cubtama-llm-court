"""llm-court CLI のエントリポイント。"""

import asyncio
import logging
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from llm_court.config import ConfigError, Role, Settings, load_models_config
from llm_court.llm import InMemoryRecorder, LLMClient, LLMConnectionError, PromptLoader
from llm_court.llm.backend import OpenAIChatBackend
from llm_court.llm.bench import BenchRow, run_bench
from llm_court.llm.client import BackendFactory

app = typer.Typer(
    help="LLM 法廷バトルゲーム llm-court の CLI。",
    no_args_is_help=True,
)
config_app = typer.Typer(help="設定ファイルの確認。", no_args_is_help=True)
app.add_typer(config_app, name="config")

console = Console()

# テストでフェイクに差し替えるため、モジュール属性として持つ
backend_factory: BackendFactory = OpenAIChatBackend.from_provider


@app.callback()
def main() -> None:
    settings = Settings()
    logging.basicConfig(level=settings.log_level)
    # HTTP クライアントのリクエストごとのログは Rich の表示を埋めるので抑える
    for name in ("httpx", "httpx2", "httpcore", "httpcore2", "openai"):
        logging.getLogger(name).setLevel(logging.WARNING)


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


if __name__ == "__main__":
    app()
