# 0003: SearXNG のローカル構成

- 日付: 2026-09-23
- 状態: 採用

## 背景

ディベート型の捜査パイプライン(Phase 2)はセルフホストの SearXNG を使う。Phase 0 で起動構成を用意する。

## 決定

- `infra/docker-compose.yml` で公式イメージ `searxng/searxng` を起動し、`127.0.0.1:8080` にのみ公開する
- `infra/searxng/settings.yml` を同梱: `use_default_settings: true` をベースに `search.formats` に `json` を追加、`default_lang: ja`
- `server.limiter: false`(ローカル専用で、プログラムからの連続クエリがボット判定されるのを避ける)
- `secret_key` は環境変数 `SEARXNG_SECRET`(`infra/.env`、git 管理外)で与える
- backend からの接続先は `LLM_COURT_SEARXNG_URL`(既定 `http://localhost:8080`)

## 理由

- ローカルホストのみにバインドすることで、limiter 無効でも外部から悪用されない

## 影響

- イメージは `latest` 指定。挙動が変わった場合はタグを固定する
