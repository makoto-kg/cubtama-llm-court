# 0009: 分析官と人間 vs LLM

- 日付: 2026-09-26
- 状態: 採用

## 背景

Phase 6 で、人間がセリフを入力せず、分析官(analyst)が示す選択肢を選ぶだけでディベートに参加できるようにする。罠を見抜くゲーム性と、選択の公平性(強さを事前に見せない)を両立させる必要があった。

## 決定

### 選択肢のモデル(PLAN §4 の `ContradictionCandidate` を一般化)
- フェーズによって必要な選択肢が違うため、`ChoiceOption` にまとめ、`kind` で区別する
  - `contradiction`(反論): 中身は PLAN どおりの `ContradictionCandidate`(`target_claim_id`、`evidence_id | other_claim_id`、`type`、`strength`)
  - `probe`(反論の「ゆさぶる」): 相手の主張に説明を求める。減点なし
  - `argument`(冒頭陳述・最終弁論): 証拠品に基づく論点の方針。減点なし
- 表示用の `label`(どの主張に/何をつきつけて/どの論法で)は、ID と型からコードで組み立てる。LLM には書かせない
- 見せる文(`pitch`)と、強さの判断理由(`rationale`)を分ける

### 分析官の出力の検証
- `ContradictionOutput` を Pydantic で検証する。strong を 1 つ以上、weak・trap のどちらかを 1 つ以上含まなければ検証エラーにして再試行させる
- 存在しない主張 ID・証拠品 ID を参照する候補は捨てて、その数を `ChoicesPrepared.discarded` に記録する。証拠品 ID の表記ゆれは正規化する(正規化は依存の向きを守るため domain に置く)
- 矛盾候補を作れない場合(再試行の上限や、有効な候補が 2 つ未満)は、論点の方針に切り替えて試合を続ける
- 相手の直前の発言に引用の問題(`unknown_evidence` / `unsupported_quote`)があれば、規則で `fabricated_citation` の strong 候補を追加する
- 強さが並び順から推測されないよう、候補はセッションと手番から決まる順に混ぜる(再現可能)

### 進行とイベント
- `SessionStarted` に `human_side` と `penalty_gauge`(開始時のモード定義)を記録する
- 新しいイベント
  - `ChoicesPrepared`: 選択肢
  - `ChoiceMade`: 選んだ選択肢。強さを含む
  - `PenaltyApplied`: 減点量と残量
- `Verdict.decided_by` に `judge` / `penalty` を追加した
- 人間の手番では、エンジンが選択肢を用意して止まる。相手(LLM)の発言と主張抽出が終わったら、同じステップ内で分析官を走らせる(先行実行)
- `choose` の処理: weak なら −1、trap なら −2 を減点する(値はモード定義)。ゲージが 0 以下なら判決フェーズに移って相手の勝ちとし、代弁者は呼ばない。そうでなければ、代弁者(advocate)が選択肢をそのまま発言に清書する(内容を強めたり弱めたりしない)
- 状態の検証として、人間側の発言は選択の後にしか記録できない

### 公平性(強さの秘匿)
- ストアには完全な形で保存する
- 未選択の `ChoicesPrepared` の `strength`・`rationale`・`source` は、API のレスポンス・`/events`・SSE(新着と履歴)で伏せる(`None` にする)
- 選択した後は伏せない(学習用に、同じ手番のほかの候補の強さも公開する)
- 伏せた状態を表すため、ドメインモデルの `strength` / `rationale` / `source` は None を取れる型にした

### API
- `POST /sessions` に `human_side` を追加した
- `GET /sessions/{id}/choices`: 伏せた選択肢を返す
- `POST /sessions/{id}/choices`: 選択 → 清書 → 次の人間の手番か判決まで進行、をバックグラウンドで行う。手番外は 409、存在しない選択肢は 422
- `SessionView` と `NextTurn.by_human` に人間 vs LLM の情報を追加した

### 評価(分析官の候補精度)
- `EvalSpec.analyst: true` にすると、完了した各ディベートの反論・最終弁論の各発言に対し、相手側の立場で矛盾候補を作らせる。その時点までの文脈で再現する
- 各候補の強さを、検証役(`judge` 役、`prompts/judge/verify_candidate.j2`)が独立に判定する
- 指標
  - 罠の混入率(trap を含むセットの割合)
  - 強さの分布
  - 強い候補の妥当性(検証役も strong とした割合)
  - 罠の一致率
  - 参照不正率
  - 規則による候補の数

## 理由

- 表示用の文言と参照をコードで組み立てると、LLM の出力が崩れても選択肢の意味(何をつきつけるか)が崩れない
- 強さを秘匿しつつイベントログには真実を残すことで、再構築・評価・リプレイの前提を保ったままゲームとして公平にできる

## 影響

- 分析官と検証役が同じモデル(`models.local.yaml` の全役割 gpt-oss-20b)だと、妥当性の指標は自己評価に近くなる。参照用裁判長や別構成との比較で補う
- 初回の実測(gpt-oss-20b、1 テーマ)
  - 罠の混入率 100%
  - 強い候補の妥当性 40%
  - 罠の一致率 17%
  - 分析官の strong・trap の判定は検証役とあまり一致せず、プロンプト改善の余地が大きい
- 規則による候補は `unsupported_quote`(「」内の言い回しの違い)でも strong になるため、言い換え程度の引用も「捏造」として指摘できてしまう
