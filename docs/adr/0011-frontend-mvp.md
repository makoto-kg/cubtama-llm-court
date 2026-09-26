# 0011: Frontend MVP(SPA・API 連携・思考ログ)

- 日付: 2026-09-26
- 状態: 採用

## 背景

Phase 7 で、法廷バトル ADV としてブラウザで遊べる画面を作る。ユーザーからは Node.js 24 を使うこと、SPA としてビルドできることを指定された。思考ログ(LLM の入出力)の表示には、バックエンドでの記録の追加も必要だった。

## 決定

### フロントエンドの構成
- Next.js 16(App Router)、TypeScript strict、Tailwind CSS 4、Zustand、Vitest。pnpm は `packageManager` で固定する
- Node.js 24 を使う
  - `frontend/.tool-versions`(asdf)で 24.15.0 に固定し、`engines.node` は `>=24`
- SPA として静的にビルドする
  - `next.config.ts` を `output: "export"` にする(`trailingSlash: true`、`images.unoptimized`)。`pnpm build` で `out/` に静的な SPA が出力され、任意の静的サーバーで配信できる
  - サーバーで動く機能は使わない: API Route、Server Actions、リクエスト時のサーバー fetch、middleware、Proxy、画像最適化
  - 動的パスは使わず、セッションはクエリで渡す(`/court/?session=<id>`)。`useSearchParams` を使う部分は `Suspense` で包む(静的ビルドの要件)
  - Server Components はビルド時に描画するシェル(レイアウト・固定の見出し)にだけ使う。データを扱う画面は Client Components にし、ブラウザから API を呼ぶ
- API の型は `pnpm gen:api` で生成する。手書きの型は使わない
  - 生成の流れ: backend の `llm-court openapi` → `src/api/openapi.json` → `openapi-typescript` → `src/api/schema.d.ts`
  - クライアントは openapi-fetch。生成物はコミットする
- 接続先は `NEXT_PUBLIC_API_ORIGIN`(既定 `http://127.0.0.1:8000`)。バックエンドの CORS は `http://localhost:3000` を既定で許可している
- 状態の真実はバックエンド
  - `debate` / `task` のイベントを受けたら `GET /sessions/{id}` を取り直す
  - クライアントが持つのは、表示用の派生状態(ストリーミング中の文、進捗、カットイン)だけ
- API の呼び出しと SSE の処理は `hooks/` と `store/` に置き、コンポーネントは表示に専念する
- SSE は EventSource で受ける。判決・中断のイベントで接続を閉じる(自動再接続を止める)。それ以外の切断では EventSource が `Last-Event-ID` を付けて再接続する
- 対戦モードでは、LLM 側の手番を自動で進める(人間の手番で止まる)

### 画面と演出
- 画面: `/`(タイトル)、`/court/?session=`(捜査 → 法廷 → 判決)、`/settings/`(モデルの割り当て)
- 立ち絵はオリジナルの仮素材(SVG)にする。パスは `src/assets/manifest.ts` の 1 か所で管理する
- カットインの文言はオリジナルにし、既存作品の決め台詞は使わない
  - 人間がつきつけたとき「反証!」
  - ゆさぶったとき「確認!」
  - LLM 側の反論の開始時「反論!」
- 思考ログは、ゲーム内の「書記官の記録」として常に表示できるパネルにする

### バックエンドの追加
- `LLMCallRecord` / `LLMCallInfo` に次を追加した(`Settings.llm_record_io` で無効にできる)
  - `messages`: 最後の試行のリクエスト
  - `response_text`: 生出力
  - `reasoning_text`: 思考部分。`llm_record_reasoning_max_chars` で上限をかける
  - `parsed`: 構造化出力のパース結果
- 未選択の手番の分析官の呼び出しの出力(`response_text` / `reasoning_text` / `parsed`)は、強さを含むため、選ぶまで API・`/events`・SSE で伏せる(ADR 0009 の秘匿を拡張)
- 同梱の捜査結果を選べるようにした: `GET /api/evidence-samples` と `POST /api/sessions/{id}/evidence/samples/{name}`。対象は `Settings.sample_evidence_dir`(既定 `eval/evidence`)で、名前は一覧にあるものだけ受け付ける(パスは受け取らない)
- `GET /api/config`: 役割ごとの割り当て。api_key は返さない
- 捜査中、証拠品候補が見つかるたびに `progress` へ「証拠品候補: <タイトル>」を流す
- `SessionView.penalty_gauge_max`: ゲージの最大値もバックエンドから返す(クライアントでルールを持たない)

## 理由

- SPA にしておくと、バックエンド(FastAPI)と別に、任意の静的サーバーで配信できる。Next.js を BFF として使わない方針(frontend/AGENTS.md)とも合う
- 思考ログをゲームの機能として出すには入出力の記録が必要。その記録から強さが漏れないよう、秘匿の範囲も合わせて広げた

## 影響

- イベントに入出力が入るため、1 試合あたりの DB と JSONL のサイズが大きくなる(数百 KB 程度)
- Playwright による E2E は未導入。ブラウザでの確認は手順として README に書いた
