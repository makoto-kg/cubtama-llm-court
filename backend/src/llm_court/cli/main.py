"""llm-court CLI のエントリポイント。"""

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from llm_court.config import ConfigError, Role, Settings, load_models_config

app = typer.Typer(
    help="LLM 法廷バトルゲーム llm-court の CLI。",
    no_args_is_help=True,
)
config_app = typer.Typer(help="設定ファイルの確認。", no_args_is_help=True)
app.add_typer(config_app, name="config")

console = Console()


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


if __name__ == "__main__":
    app()
