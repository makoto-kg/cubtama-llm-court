"""完全オフラインモードのパック(`llm-court offline ...`)。"""

import asyncio
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from llm_court.config import ConfigError, Settings
from llm_court.engine.recorder import BufferedRecorder
from llm_court.llm import LLMClient, LLMError, PromptLoader
from llm_court.modes import TRIAL_MODE
from llm_court.offline.models import OfflinePack
from llm_court.offline.scripted import ScriptedScenarioError, build_scripted_pack, load_scenario
from llm_court.offline.simulate import OfflineSimulator, build_index
from llm_court.scenario.store import CaseNotFoundError, CaseStore

offline_app = typer.Typer(
    help="完全オフラインモード(裁判型)のパック。事前に被告の応答を生成する。",
    no_args_is_help=True,
)
console = Console()

INDEX = "index.json"
CASES_DIR = "cases"


def _client(settings: Settings, recorder: BufferedRecorder) -> LLMClient:
    from llm_court.cli import main as cli  # 実行時に読む(テストでの差し替えと循環 import の回避)

    try:
        return LLMClient.from_settings(
            settings, backend_factory=cli.backend_factory, recorder=recorder
        )
    except ConfigError as e:
        console.print(f"[red]設定エラー:[/red] {e}")
        raise typer.Exit(code=1) from e


def load_packs(out_dir: Path) -> list[OfflinePack]:
    directory = out_dir / CASES_DIR
    if not directory.is_dir():
        return []
    return [
        OfflinePack.model_validate_json(p.read_text(encoding="utf-8"))
        for p in sorted(directory.glob("*.json"))
    ]


def write_index(out_dir: Path) -> Path:
    path = out_dir / INDEX
    path.write_text(build_index(load_packs(out_dir)).model_dump_json(indent=2) + "\n", "utf-8")
    return path


@offline_app.command("export")
def export(
    case_ids: Annotated[list[str], typer.Argument(help="パックにする事件の ID(複数可)")],
    out: Annotated[
        Path | None,
        typer.Option(
            "--out", "-o", help="出力先(既定は offline_output_dir = frontend/public/offline)"
        ),
    ] = None,
    retries: Annotated[
        int, typer.Option("--retries", min=0, help="逸脱した応答を作り直す回数")
    ] = 2,
    no_check: Annotated[
        bool, typer.Option("--no-check", help="逸脱の検査をしない(作り直しもしない)")
    ] = False,
) -> None:
    """事件の全行動に対する被告の応答を事前に生成し、フロントエンドだけで遊べるパックにする。"""
    settings = Settings()
    store = CaseStore(settings.scenario.case_dir)
    try:
        cases = [store.load(cid) for cid in case_ids]
    except CaseNotFoundError as e:
        console.print(f"[red]事件 {e} はありません[/red]")
        raise typer.Exit(code=1) from e
    out_dir = out or settings.offline_output_dir
    recorder = BufferedRecorder()
    client = _client(settings, recorder)
    simulator = OfflineSimulator(
        llm=client,
        prompts=PromptLoader(settings.prompts_dir),
        mode=TRIAL_MODE,
        retries=retries,
        check_deviations=not no_check,
    )

    async def run() -> list[OfflinePack]:
        packs: list[OfflinePack] = []
        async with client:
            with console.status("被告の応答を生成しています…") as status:
                for case in cases:
                    packs.append(await simulator.build(case, on_progress=status.update))
                    recorder.drain()  # 記録は各応答に入れてあるので捨てる
        return packs

    try:
        packs = asyncio.run(run())
    except LLMError as e:
        console.print(f"[red]生成できませんでした:[/red] {escape(str(e))}")
        raise typer.Exit(code=1) from e

    (out_dir / CASES_DIR).mkdir(parents=True, exist_ok=True)
    table = Table(title="オフラインパック")
    for column in ("ID", "タイトル", "応答", "逸脱が残った応答", "未検査", "作り直し"):
        table.add_column(column)
    for pack in packs:
        path = out_dir / CASES_DIR / f"{pack.case.id}.json"
        path.write_text(pack.model_dump_json() + "\n", encoding="utf-8")
        meta = pack.meta
        table.add_row(
            pack.case.id,
            escape(pack.case.title),
            str(meta.responses),
            str(meta.deviations),
            str(meta.unchecked),
            str(sum(r.attempts - 1 for r in pack.responses)),
        )
    console.print(table)
    console.print(f"保存しました: {write_index(out_dir)}")


@offline_app.command("scripted")
def scripted(
    paths: Annotated[
        list[Path], typer.Argument(help="台本のシナリオファイル(YAML。複数可)", exists=True)
    ],
    out: Annotated[
        Path | None,
        typer.Option(
            "--out", "-o", help="出力先(既定は offline_output_dir = frontend/public/offline)"
        ),
    ] = None,
) -> None:
    """人が書いた事件と応答(台本)から、LLM を使わずにオフラインパックを作る(チュートリアル用)。"""
    out_dir = out or Settings().offline_output_dir
    packs: list[OfflinePack] = []
    for path in paths:
        try:
            packs.append(build_scripted_pack(load_scenario(path), TRIAL_MODE))
        except (ScriptedScenarioError, ValidationError) as e:
            console.print(f"[red]{escape(str(path))} を読めません:[/red]\n{escape(str(e))}")
            raise typer.Exit(code=1) from e
    (out_dir / CASES_DIR).mkdir(parents=True, exist_ok=True)
    for pack in packs:
        path = out_dir / CASES_DIR / f"{pack.case.id}.json"
        path.write_text(pack.model_dump_json() + "\n", encoding="utf-8")
        console.print(f"{escape(pack.case.title)}: 応答 {pack.meta.responses} 件 → {path}")
    console.print(f"保存しました: {write_index(out_dir)}")


@offline_app.command("list")
def list_packs(
    out: Annotated[
        Path | None, typer.Option("--out", "-o", help="パックの場所(既定は offline_output_dir)")
    ] = None,
) -> None:
    """同梱しているオフラインパックの一覧。"""
    packs = load_packs(out or Settings().offline_output_dir)
    if not packs:
        console.print("オフラインパックはまだありません")
        return
    table = Table(title="オフラインパック")
    for column in ("ID", "タイトル", "矛盾", "応答", "逸脱", "生成"):
        table.add_column(column)
    for p in packs:
        table.add_row(
            p.case.id,
            escape(p.case.title),
            str(len(p.answers.contradictions)),
            str(p.meta.responses),
            str(p.meta.deviations),
            p.meta.generated_at.strftime("%Y-%m-%d %H:%M"),
        )
    console.print(table)
