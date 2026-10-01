# 0021: frontend を GitHub Pages にデプロイする

- 日付: 2026-10-01
- 状態: 採用

## 背景

frontend は `output: "export"` の SPA で、既定のオフラインモード(ADR 0014・0018)はバックエンドなしで遊べる。
静的ホスティングで公開できるよう、GitHub Pages へのデプロイの設定を用意したい。

GitHub Pages のプロジェクトサイトは `https://<owner>.github.io/<repo>/` のサブパスで配信される。
Next.js の `basePath` は `next/link` には自動で付くが、`next/image` の `src` と `fetch` の URL には付かない。

## 決定

- `.github/workflows/deploy-frontend.yml` で GitHub Actions からデプロイする
  - `master` への push(`frontend/` か workflow 自身の変更)と手動実行で動く
  - lint・型チェック・テストのあと `pnpm build` し、`frontend/out` を Pages の artifact としてアップロードする
  - リポジトリの Settings → Pages の Source を「GitHub Actions」にしておく
- サブパスは環境変数 `NEXT_PUBLIC_BASE_PATH` で渡す(既定は空 = ルートに配信)
  - `next.config.ts` の `basePath` に使う
  - workflow では `actions/configure-pages` の `base_path` を渡す(カスタムドメインなら空になる)
  - `next/image` の `src` と `fetch` の URL には `src/lib/basePath.ts` の `withBasePath` で付ける
    (`src/assets/manifest.ts`・`src/lib/offline/config.ts`)

## 理由

- 配信の場所はビルド時に決まる値で、画面の切り替えではない(ADR 0018 の「ビルドは 1 本」と矛盾しない)
- 接頭辞を付ける場所を素材の manifest とオフラインパックの設定の 2 か所に寄せておけば、他のコードは変えずに済む

## 影響

- 公開されるのはオフラインモードとして遊べる画面。オンラインモードは `NEXT_PUBLIC_API_ORIGIN`(既定 `http://127.0.0.1:8000`)のバックエンドに、閲覧者のブラウザからつなぐ
- `fetch` や `next/image` で `public/` のファイルを新しく参照するときは `withBasePath` を通す
