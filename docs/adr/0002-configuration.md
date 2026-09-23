# 0002: 設定の読み込みと models.yaml のスキーマ

- 日付: 2026-09-23
- 状態: 採用

## 背景

設計原則「役割とモデルを分離」を実現するため、`config/models.yaml` のスキーマと、アプリ全体の設定の置き場所を決める必要があった。

## 決定

- アプリ設定は pydantic-settings の `Settings`(`llm_court.config.settings`)。環境変数 `LLM_COURT_*` と `backend/.env` から読む
- `models.yaml` は `providers` / `models` / `roles` の3セクション(PLAN §5 の形そのまま)を Pydantic モデル `ModelsConfig` で検証する
  - 未知のキーはエラー(`extra="forbid"`)。typo を黙って無視しない
  - 参照整合性を検証する: model → provider、role → model が定義済みであること
  - `roles` は `Role` 列挙(9役割)の全割り当てを必須とする
  - `api_key` は `SecretStr`。値中の `${ENV_VAR}` を環境変数で展開し、未設定ならエラー
- 役割からの解決は `ModelsConfig.resolve(role)` に集約する
- PLAN §2 の `config/settings.example.yaml` は作らず、`backend/.env.example` で代替する

## 理由

- 設定の置き場所を「構造的な割り当て = YAML」「環境依存の値・秘密 = 環境変数」に分けると、YAML をそのままコミットできる
- 全役割の割り当て必須にしておくと、実行時に「役割にモデルがない」エラーが起きない

## 影響

- 役割を追加するときは `Role` と `models.yaml` を同時に更新する必要がある
- PLAN §2 のリポジトリ構成図の `settings.example.yaml` を `.env.example` に更新する(要プラン更新)
