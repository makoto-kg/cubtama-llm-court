# llm-court

法廷バトルADVの雰囲気で、LLM がテーマについて論戦するゲームです。LLM 同士の対戦(観戦・比較検証)と、人間 vs LLM の対戦ができます。人間はセリフを入力せず、分析官 LLM が示す選択肢を選んで戦います。

LLM は OpenAI 互換 API(LM Studio 等)だけを使い、完全ローカルで動かすことを前提にしています。

- 設計とロードマップ: [docs/PLAN.md](docs/PLAN.md)
- 設計判断の記録: [docs/adr/](docs/adr/)
- 開発者向けのルールとコマンド: [AGENTS.md](AGENTS.md)、[backend/AGENTS.md](backend/AGENTS.md)


## 必要なもの

- Python 3.12 以上と [uv](https://docs.astral.sh/uv/)
- OpenAI 互換の LLM サーバー(既定は LM Studio の `http://localhost:1234/v1`)
- (捜査を行う場合のみ)SearXNG。`infra/docker-compose.yml` で起動できる

## セットアップ

```bash
cd backend
uv sync
```

### モデルの割り当て

使うモデルは `backend/config/models.yaml` で役割ごとに割り当てます。手元だけで割り当てを変えたい場合は、git 管理外の `config/models.local.yaml` を作り、環境変数で指定します。

```yaml
# backend/config/models.local.yaml の例(全役割を 1 つのモデルに割り当てる)
providers:
  local:
    base_url: http://localhost:1234/v1
    api_key: "not-needed"
    capabilities: {json_schema: true, json_mode: false, tool_calling: false, streaming: true}
    max_concurrency: 2
models:
  fast:
    provider: local
    model: "openai/gpt-oss-20b"   # LM Studio 上のモデル ID
    reasoning: low
roles:
  researcher: fast
  scenario_writer: fast
  solver: fast
  judge: fast
  analyst: fast
  claim_extractor: fast
  debater: fast
  advocate: fast
  witness: fast
```

```bash
export LLM_COURT_MODELS_CONFIG_PATH=config/models.local.yaml
uv run llm-court config check   # 割り当てを確認
```

以降のコマンドはすべて `backend/` で実行します。

## ブラウザで遊ぶ

バックエンドの API サーバーと、フロントエンドの開発サーバーを起動します(フロントエンドは Node.js 24 と pnpm が必要)。

```bash
# ターミナル 1(backend/)
uv run llm-court serve

# ターミナル 2(frontend/)
pnpm install
pnpm dev
```

http://localhost:3000 を開きます。

1. **タイトル**: モード(対戦 = 人間 vs LLM / 観戦 = LLM vs LLM)、あなたの陣営、証拠品の入手方法(同梱の捜査結果 / JSON ファイル / Web で捜査)、論題、反論の往復数を選んで「開廷」
2. **捜査**(Web で捜査を選んだ場合): 進捗と、見つかった証拠品候補が増えていく
3. **法廷**: 発言がタイプライター表示で流れる
   - 観戦: 「次へ」または「判決まで自動で進める」
   - 対戦: LLM 側は自動で進み、あなたの番で選択肢が出る
   - 右側の「書記官の記録(思考ログ)」には、LLM への入力・生出力・パース結果・トークン数・レイテンシが表示される
   - 「証拠品ファイル」で証拠品を確認できる
4. **判決**: 勝敗、2 回の評価の採点表、裁判長の理由、あなたの選択(強さの公開)、計測、法廷記録

### 裁判(事件を解く)

タイトルでモード「裁判(事件を解く)」を選ぶと、`llm-court case generate` で生成し、solver の検証に合格した事件の一覧が出ます。「開廷」で始めます。

1. **証言**: 証人の証言が行ごとに表示される。各行の下に、分析官が用意した選択肢が並ぶ
   - **つきつける**: その行に証拠品をつきつける。正解なら証人が崩れる(「証言崩壊!」)。はずれはゲージ −1、罠(よくある誤解を突いた、もっともらしい組)は −2
   - **ゆさぶる**: その行を詳しく説明させる。減点なし。証人は嘘を保ったまま言い逃れる
2. **証人の応答**: 証人(LLM)が台本の範囲で即興で答え、タイプライター表示で流れる。「証拠品ファイル」で証拠品と登場人物を確認できる
3. **最後の問い**: すべての矛盾を解くと、事件の問い(誰が・何を)に答える
4. **解説**: 閉廷後、矛盾ごとに正解の理由、決め手の知識(出典の URL と引用、最近覆った知識なら以前の通説)、罠と「なぜ選びたくなるか」が表示される
   - 解説の誤りを見つけたら「解説に異議あり」で項目を選んで報告できる(イベントとして記録される)
   - 尋問の記録(台本からの逸脱の判定付き)と思考ログは、台本と真相を含むため閉廷後に公開される

`/settings/` で役割ごとのモデル割り当てを確認できます。フロントエンドは `pnpm build` で SPA として `frontend/out/` にビルドでき、`npm run serve`(または任意の静的サーバー)で配信できます(接続先は `NEXT_PUBLIC_API_ORIGIN`)。

## CLI で遊ぶ(人間 vs LLM)

`llm-court play` は、バックエンドだけで人間 vs LLM を遊べる簡易モードです。本格的なゲーム画面ではなく、シナリオ(分析官の選択肢、代弁者の清書、ペナルティの動き)を手早く確認するためのものです。

```bash
uv run llm-court play "週休3日制を導入すべきか" \
  --side affirmative \
  --evidence eval/evidence/four-day-week.json
```

### 流れ

1. 開廷して証拠品をそろえる。`--evidence` を付けると既存の捜査結果を使い、付けなければ Web で捜査する(SearXNG が必要)
2. LLM 側の発言がストリーミングで表示される
3. あなたの手番になると、分析官が用意した選択肢が表で表示される。番号を入力して選ぶ
   - 冒頭陳述・最終弁論: **方針**(どの証拠品で何を主張するか)
   - 反論: **つきつける**(相手の主張の矛盾を指摘する)と **ゆさぶる**(相手に説明を求める)
4. 選んだ内容を、代弁者があなた側の発言として清書する
5. 反論で選んだ指摘の強さ(strong / weak / trap)は、選んだ後に公開される。weak を選ぶとペナルティゲージが 1、trap(実は矛盾していない罠)を選ぶと 2 減る。ゲージが 0 になると負け
6. 最終弁論の後、裁判長が採点して判決を出す。提示順を入れ替えて 2 回評価し、勝者が割れたら引き分けになる

### オプション

| オプション | 内容 |
|---|---|
| `--side`, `-s` | あなたが担当する陣営。`affirmative`(肯定側)/ `negative`(否定側、既定) |
| `--rounds`, `-r` | 反論の往復数(既定 1) |
| `--evidence`, `-e` | 既存の捜査結果 JSON。指定すると捜査を省略する |
| `--reveal` | 選ぶ前に各選択肢の強さと判断理由を表示する(シナリオ検証向け) |
| `--resume <セッション ID>` | 中断したセッションを再開する(論題は不要) |

- 選択の入力で `q` を入力すると中断し、再開用のコマンド(`llm-court play --resume <ID>`)が表示されます
- 終了すると、イベントログ(JSONL)と法廷記録(Markdown)を `backend/data/debates/` に保存し、ターンごとの待ち時間などの計測サマリを表示します

### 証拠品(捜査結果)

`eval/evidence/` に、すぐ試せる捜査結果を同梱しています。

- `basic-income.json`: 日本はベーシックインカムを導入すべきか
- `four-day-week.json`: 週休3日制を導入すべきか

新しいテーマの証拠品は `llm-court research "<テーマ>"` で作れます(SearXNG が必要)。結果は `data/research/` に保存され、`--evidence` に渡せます。

## オフラインで遊ぶ(バックエンド不要)

裁判型は、バックエンドも LLM サーバーもなしで、フロントエンドだけで遊べます。事件の全行動に対する証人の応答を事前に LLM で生成したパックを、`frontend/public/offline/` に同梱しています。一覧の先頭のチュートリアル「消えたチュール事件」(猫の事件)から始めると、遊び方がわかります。

```bash
cd frontend
pnpm dev                 # http://localhost:3000/offline/
# または、配布用に静的ビルド(タイトルがオフラインの一覧になる)
NEXT_PUBLIC_OFFLINE_ONLY=1 pnpm build
npm run serve            # out/ を http://127.0.0.1:8080 で配信(PORT・HOST で変更可。任意の静的サーバーでもよい)
```

- 進行はブラウザに保存され、再読み込みしても続きから遊べる(「最初からやり直す」で消せる)
- 「解説に異議あり」はブラウザに保存され、JSON で書き出せる
- 新しい事件のパックは `uv run llm-court offline export <事件の ID...>` で作る(backend/)
  - 全行動の応答を生成し、台本からの逸脱を検査して、逸脱した応答は作り直す(`--retries`)
- 応答を人が書く台本の事件(チュートリアルなど)は、`backend/scenarios/` の YAML から `uv run llm-court offline scripted <ファイル...>` で作る(LLM は使わない)

## CLI で遊ぶ(裁判)

`llm-court trial` は、生成済みの事件をバックエンドだけで遊ぶ簡易モードです(シナリオ検証用)。

```bash
uv run llm-court case list                 # 事件の ID を確認する
uv run llm-court trial <事件の ID> --reveal  # --reveal で選択肢の強さと台本の判定も表示する
```

- 証言と選択肢が表示されるので、番号で選ぶ。`e` で証拠品の一覧、`q` で中断(`llm-court trial --resume <ID>` で再開)
- 全矛盾を解いたら最後の問いに答え、閉廷後に解説を表示する。イベントログは `backend/data/debates/trial-<ID>.jsonl` に保存する

`llm-court eval-trial <事件の ID...> --runs N` は、決まった方針の自動プレイヤーで事件を遊び、証人の台本逸脱率(崩れるべきでない場面での自白、崩れ損ね、隠している事実の漏洩)を測ります。レポートは `data/eval/` に Markdown と CSV で出力します。

## そのほかの CLI

| コマンド | 内容 |
|---|---|
| `llm-court debate "<テーマ>" -r 3 [-e 捜査結果.json]` | LLM 同士のディベートを判決まで観戦する |
| `llm-court research "<テーマ>"` | テーマを Web で調べ、引用を検証した証拠品を作る |
| `llm-court bench -n 3 -r debater` | 役割に割り当てたモデルの速度と構造化出力の成功率を測る |
| `llm-court eval eval/specs/example.yaml` | 複数のモデル構成を同じテーマで比較したレポートを作る |
| `llm-court case generate "<テーマ>" [-e 捜査結果.json]` | 裁判型の架空の事件を生成し、整合性チェックと solver で検証して `data/cases/` に保存する(`case validate` / `case list` もある) |
| `llm-court serve` | API サーバー(REST + SSE)を起動する(`http://127.0.0.1:8000/docs`)。ブラウザ版はこれに接続する |

`uv run llm-court --help` と、各コマンドの `--help` で詳細を確認できます。
