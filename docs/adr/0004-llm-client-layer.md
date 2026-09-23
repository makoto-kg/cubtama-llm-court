# 0004: LLM クライアント層の設計

- 日付: 2026-09-23
- 状態: 採用

## 背景

Phase 1 で、どの OpenAI 互換サーバーでも同じように呼べる計測付きの LLM 層(`llm_court.llm`)を作る。
構造化出力の対応状況や思考部分(reasoning)の返し方はサーバー・モデルごとに異なる。

## 決定

### 通信の抽象化
- `LLMClient` は `ChatBackend` プロトコル(`stream` / `complete` / `aclose`)越しにサーバーを呼ぶ。本番実装は openai 公式 SDK の `OpenAIChatBackend`。テストは録画済み応答(`tests/fixtures/llm/`)を返す `FakeChatBackend` に差し替える
- SDK 側の自動リトライは無効(`max_retries=0`)にし、再試行は `LLMClient` で制御する
- SDK の例外は `LLMConnectionError`(接続・タイムアウト)/ `LLMRequestRejectedError`(400・422)/ `LLMError` に変換する
- プロバイダが `streaming: true` なら常にストリーミングで呼ぶ(構造化出力も)。TTFT を一律に測るため

### 構造化出力
- 試すモードは能力フラグから `json_schema`(`capabilities.json_schema`)→ `json_object`(`capabilities.json_mode`)→ `prompt` の順に組み立てる。`json_mode` フラグを新設した
- サーバーがリクエストを拒否(400/422)したら次のモードへ降格する。降格は再試行回数に数えない
- JSON の抽出や Pydantic の検証に失敗したら、直前の出力(思考部分を除く)とエラー内容を会話に追加して同じモードで再試行する。上限は `Settings.llm_structured_max_retries`(既定 2)
- 上限超過・全モード拒否は `StructuredOutputError`。接続エラーは再試行せずにそのまま送出する
- `json_object` / `prompt` モードでは、スキーマ指示を system メッセージの末尾に足す(固定部分を先頭に保つため)。指示文とフィードバック文も `prompts/llm/` のテンプレートにする

### 前処理
- 思考部分は、サーバーが `reasoning_content` / `reasoning` として分けて返す場合は本文に含めない。本文に `<think>…</think>` が混ざる場合は除去する
- ストリーミング用の `ThinkFilter` はチャンク境界をまたぐタグも除去する。開きタグのない `</think>` は、ストリーミングでは既に送出済みの部分を取り消せないため、タグだけを除去する
- JSON 抽出はコードフェンスや前後の説明文を無視し、最初にパースできた JSON オブジェクトを使う

### 計測
- 1 回の論理呼び出し(構造化出力の再試行を含む)につき `LLMCallRecord` を 1 件、`CallRecorder` に渡す。内容はロール、モデル、プロンプト名とバージョン、TTFT、総時間、入出力トークン、tok/s、成否、試行回数、再試行回数、エラー
- TTFT は最初の試行でセマフォ取得後から最初のトークン(思考部分を含む)まで。総時間には待ち時間と全試行を含む。tok/s は出力トークン合計を初トークン以降の生成時間の合計で割る
- イベント `LLMCallRecorded` への変換は、イベントストアを作る Phase 3 で `CallRecorder` の実装として行う

### その他
- 並列度はプロバイダごとの `asyncio.Semaphore(max_concurrency)` で制御する
- `ModelConfig.reasoning` は `reasoning_effort` として送る
- プロンプトは `{% block system %}` / `{% block user %}` で system / user に分ける。バージョンはテンプレートファイルの SHA-256 先頭 12 桁。`include` した先の変更はバージョンに反映されない
- `ProviderConfig.timeout_s`(既定 300 秒)を追加した

## 理由

- バックエンドを抽象化すると、実サーバーなしでフォールバックと再試行の分岐をすべて単体テストできる
- 再試行と降格を LLM 層に閉じ込めると、agents 側は検証済みの Pydantic モデルだけを扱える

## 影響

- ベンチマーク(`llm-court bench`)は同じモデルに割り当てた役割をまとめて 1 回だけ計測する
- 役割ごとに温度などの呼び出しパラメータが必要になったら `ModelConfig` に追加する
