# backend

Python(FastAPI)によるゲームエンジン、LLM層、検索パイプライン、CLI、API。
リポジトリ全体のルールはルートの `AGENTS.md` を参照。

## 環境

- Python 3.12+、パッケージ管理は uv
- ローカルLLM: OpenAI互換サーバー(既定は LM Studio の `http://localhost:1234/v1`)
- 検索: SearXNG(`infra/docker-compose.yml` で起動)
- 設定: `config/models.yaml`(プロバイダ・モデル・役割の割り当て)、`.env`(`.env.example` 参照)
  - 手元だけ割り当てを変えるときは git 管理外の `config/models.local.yaml` を作り、`LLM_COURT_MODELS_CONFIG_PATH=config/models.local.yaml` で指定する
- 生成物: `.cache/`(取得済みページ)、`data/`(捜査結果、イベントストア `llm_court.db`、ディベートの JSONL・Markdown、評価結果)。どちらも git 管理外
- 評価: `eval/specs/`(評価仕様)、`eval/evidence/`(比較に固定で使う捜査結果)

## コマンド

```bash
uv sync                                  # 依存関係のインストール
uv run ruff check --fix                  # lint(自動修正)
uv run ruff format                       # フォーマット
uv run pyright                           # 型チェック
uv run pytest -m "not integration"       # 単体テスト(実LLM・実検索なし)
uv run pytest -m integration             # 統合テスト(LLMサーバーとSearXNGが必要)
uv run llm-court --help                  # CLI
uv run llm-court config check            # models.yaml の検証と役割割り当ての表示
uv run llm-court bench -n 3 -r debater   # 役割のモデルで速度・構造化出力の成功率を計測(-r 省略で全役割)
uv run llm-court research "<テーマ>"     # 証拠品を集めて表示し data/research/ に JSON 保存(--max-chars で本文長)
uv run llm-court debate "<テーマ>" -r 3  # LLM 同士のディベート(--evidence で既存の捜査結果を使う)
uv run llm-court eval eval/specs/example.yaml  # モデル構成の比較レポートを data/eval/ に出力
uv run llm-court eval-report data/eval/<実行>  # 保存済みの評価結果からレポートを作り直す
uv run pre-commit install                # pre-commit フック(ルートの .pre-commit-config.yaml)を有効化
```

CLIサブコマンド(各フェーズで追加): `bench`(Phase 1)、`research`(Phase 2)、`debate`(Phase 3)、`eval`(Phase 4)、`case generate` / `case validate`(Phase 8)

## ディレクトリの責務(`src/llm_court/`)

| ディレクトリ | 責務 |
|---|---|
| `llm/` | OpenAI互換クライアント、役割→モデル解決、構造化出力(フォールバック・リトライ)、ストリーミング、計測 |
| `research/` | 検索クエリ生成、SearXNG検索、本文取得・抽出、証拠品化、引用検証 |
| `domain/` | Pydanticモデルとイベント定義。外部依存を持たない |
| `engine/` | 進行ステートマシン、イベントストア(SQLite)、状態の再構築 |
| `agents/` | 各役割(論者・裁判長・分析官・証人・代弁者 等)。プロンプト組み立てと出力の解釈のみを担い、状態は直接変更しない |
| `modes/` | ディベート型・裁判型のモード定義(ルーブリック、矛盾タイプ、勝利条件) |
| `scenario/` | 裁判型の事件生成・整合性チェック・solver検証 |
| `eval/` | 評価ハーネスと指標計算 |
| `api/` | FastAPI(REST + SSE)。Phase 5 以降 |
| `cli/` | Typer + Rich のCLI |

依存の向き: `domain` ← `llm` / `research` / `agents` / `modes` ← `engine` ← `api` / `cli`。`domain` から他へ依存しない。

## コーディング規約

- すべて型注釈付き。pyright のエラーを残さない
- I/O は async で統一(httpx、openai の非同期クライアント、aiosqlite)
- `print` を使わない。ログは標準の `logging`、CLI表示は Rich
- 例外は握りつぶさない。LLMの構造化出力失敗はリトライ上限後に専用の例外として上げ、`LLMCallRecorded` イベントにも失敗を記録する
- 設定値(タイムアウト、リトライ回数、並列度 等)はコードに直書きせず設定から読む

## プロンプト

- `prompts/<role>/<name>.j2` に Jinja2 テンプレートとして置く。コード内に長いプロンプト文字列を埋め込まない
- 固定部分(役割説明・ルール)をテンプレートの先頭に、可変部分(主張ログ・証拠品)を後ろに置く(サーバー側KVキャッシュの再利用のため)
- 討論ログ全文ではなく、構造化した主張ログと要約済み証拠品を渡す。発言全文は直近のもののみ
- テンプレートの変更はバージョン(ハッシュ)としてイベントに記録される。意図しない変更をしない

## テスト

- 単体テストでは実LLM・実ネットワークを呼ばない。`tests/fixtures/` の録画済み応答を返すフェイククライアントを使う
- 実LLMサーバーや SearXNG を使うテストには `@pytest.mark.integration` を付ける
- 構造化出力のフォールバック・リトライ、引用検証、イベントからの状態再構築は必ず単体テストを書く
