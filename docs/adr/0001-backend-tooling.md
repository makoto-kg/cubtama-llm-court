# 0001: Backend の開発ツール構成

- 日付: 2026-09-23
- 状態: 採用

## 背景

Phase 0 で backend の開発基盤を整える。PLAN §3 で uv / ruff / pyright / pytest の採用は決まっているが、具体的な設定値は未定だった。

## 決定

- `backend/` を uv プロジェクト(src レイアウト、hatchling ビルド)とし、`.python-version` は 3.12
- ruff: line-length 100。日本語の全角記号を誤検知する `RUF001〜003` を無効化。`T20`(print 禁止)を有効化
- pyright: `typeCheckingMode = "strict"`、対象は `src` と `tests`
- pytest: `asyncio_mode = "auto"`、`integration` マーカーを登録
- pre-commit はリポジトリルートに置き、ruff / pyright は外部リポジトリではなく `uv run --directory backend` の local フックで実行する
- 依存は各フェーズで必要になった時点で追加する(Phase 0 は typer / rich / pydantic / pydantic-settings / pyyaml のみ)

## 理由

- local フックにすると ruff / pyright のバージョンが `uv.lock` に一本化され、CI・エディタ・pre-commit で結果がずれない
- print 禁止は backend 規約(ログは logging、表示は Rich)を機械的に守るため

## 影響

- pre-commit の実行には backend の `uv sync` 済み環境が必要
