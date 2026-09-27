# frontend

Next.js(App Router)による法廷バトルADVの画面。
リポジトリ全体のルールはルートの `AGENTS.md` を参照。設計判断は `docs/adr/0011-frontend-mvp.md`。

## 技術スタック

- Next.js 16(App Router)+ TypeScript(strict)
- Tailwind CSS 4
- 状態管理: Zustand
- API クライアント: openapi-fetch(型は OpenAPI から生成)
- パッケージ管理: pnpm(`packageManager` で固定)
- Node.js 24(`.tool-versions` で固定。asdf を使う)
- テスト: Vitest(単体)、Playwright(E2E は最小限。現時点では未導入)

**Next.js 16 は学習データと API・規約が異なる場合がある。** 書く前に `node_modules/next/dist/docs/` の該当ガイドを読み、非推奨の警告に従う。

## コマンド

```bash
pnpm install
pnpm dev             # 開発サーバー(http://localhost:3000)。backend の `llm-court serve` も起動しておく
pnpm build           # SPA として静的ビルド(out/ に出力)
pnpm lint
pnpm typecheck
pnpm test
pnpm gen:api         # backend の OpenAPI から API 型を生成(src/api/schema.d.ts)
```

接続先は `NEXT_PUBLIC_API_ORIGIN`(既定 `http://127.0.0.1:8000`)。

## ルール

### SPA(静的エクスポート)

- `output: "export"` で SPA としてビルドできる状態を保つ。サーバーで動く機能は使わない
  - 使わないもの: API Route / Route Handler、Server Actions、リクエスト時のサーバー fetch、cookies・headers、middleware / Proxy、rewrites / redirects、`next/image` の最適化
- 動的パス(`[id]`)は使わず、クエリで渡す(例: `/court/?session=<id>`)。`useSearchParams` を使うコンポーネントは `Suspense` で包む
- Server Components はビルド時に描画できるシェルにだけ使い、データの取得はクライアント(ブラウザ)から API に対して行う
- 変更後は `pnpm build` が通り、`out/` に各ページの `index.html` が出ることを確認する

### 完全オフラインモード(ADR 0014)

- `/offline/` 以下の画面は API を一切呼ばない。同梱のパック(`public/offline/index.json`・`public/offline/cases/<id>.json`)を `fetch` で読む
- パックは `llm-court offline export` で作る。手で編集しない
- 進行ロジックは `src/lib/offline/` に TypeScript で移植してある(backend の `agents/trial_analyst.py`・`engine/trial.py` と同じ規則)。規則を変えるときは両方を直す
- 状態の真実は `localStorage` の行動の列。状態は `replay` で作り直す
- `NEXT_PUBLIC_OFFLINE_ONLY=1 pnpm build` で、API のない配布用の SPA になる(タイトルがオフラインの一覧になる)

### Backend との関係

- Next.js は純粋なフロントエンド。BFF層・API Route でのゲームロジック実装はしない
- API の型は `pnpm gen:api` で生成したものを使う。手書きの型定義で代用しない。backend の API を変えたら再生成する
- ゲーム状態の真実は backend のイベントログ。クライアントは表示用の派生状態のみを持ち、勝敗・ペナルティ等の判定をクライアントで行わない(例外は完全オフラインモードだけ。ADR 0014)
- ストリーミングは SSE(EventSource)で受け取り、タイプライター表示にそのまま流す

### UI・演出

- キャラクター、立ち絵、カットイン、UIはすべてオリジナルデザイン。既存作品の模倣をしない
- 素材のパスは `src/assets/manifest.ts` の一箇所で管理する(現在はオリジナルの仮素材の SVG)
- 「思考ログ」パネル(LLMの入力・生出力・パース結果・トークン数・レイテンシ)はゲームの機能として実装する。開発者用の隠し機能にしない

### コード

- Server Components を既定とし、インタラクションが必要な箇所のみ Client Components にする
- コンポーネントは表示に専念させ、API呼び出しとストリーム処理はフック(`src/hooks/`)/ストア(`src/store/`)に寄せる
- 表示用の純粋な計算は `src/lib/` に置き、Vitest で単体テストを書く
