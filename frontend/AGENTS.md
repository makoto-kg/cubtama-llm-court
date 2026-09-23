# frontend

Next.js(App Router)による法廷バトルADVの画面。**Phase 7 から着手する。それ以前はこのディレクトリに実装を追加しない。**
リポジトリ全体のルールはルートの `AGENTS.md` を参照。

## 技術スタック

- Next.js(App Router)+ TypeScript(strict)
- Tailwind CSS
- 状態管理: Zustand
- パッケージ管理: pnpm
- テスト: Vitest(単体)、Playwright(E2Eは最小限)

## コマンド(Phase 7 で整備)

```bash
pnpm install
pnpm dev             # 開発サーバー
pnpm lint
pnpm typecheck
pnpm test
pnpm gen:api         # backend の OpenAPI から API 型を生成
```

## ルール

### Backend との関係

- Next.js は純粋なフロントエンド。BFF層・API Route でのゲームロジック実装はしない
- API の型は `pnpm gen:api` で生成したものを使う。手書きの型定義で代用しない。backend の API を変えたら再生成する
- ゲーム状態の真実は backend のイベントログ。クライアントは表示用の派生状態のみを持ち、勝敗・ペナルティ等の判定をクライアントで行わない
- ストリーミングは SSE(EventSource)で受け取り、タイプライター表示にそのまま流す

### UI・演出

- キャラクター、立ち絵、カットイン、UIはすべてオリジナルデザイン。既存作品の模倣をしない
- 初期は仮素材で構わないが、差し替えやすいよう素材パスを一箇所で管理する
- 「思考ログ」パネル(LLMの入力・生出力・パース結果・トークン数・レイテンシ)はゲームの機能として実装する。開発者用の隠し機能にしない

### コード

- Server Components を既定とし、インタラクションが必要な箇所のみ Client Components にする
- コンポーネントは表示に専念させ、API呼び出しとストリーム処理はフック/ストアに寄せる
