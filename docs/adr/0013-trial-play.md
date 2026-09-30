# 0013: 裁判型のプレイ(尋問・証人・逸脱の検査・解説)

- 日付: 2026-09-27
- 状態: 採用(全矛盾を解いたあとの最後の問いは ADR 0020 でやめ、判決を言い渡す形に変更)

## 背景

Phase 8 で、solver の検証に合格した事件を `data/cases/` に生成できるようになった。Phase 9 では、それを法廷バトルとして最初から解説まで遊べるようにする。

課題は 3 つあった。
- 証人(LLM)が台本を外れる。崩れるべきでない場面で自白する、隠すべき事実を漏らす、崩れるべき場面で崩れない
- 事件には正解と台本が含まれるので、プレイヤーに見せる出力で伏せる必要がある
- 解説に出典のない説明が混ざる

## 決定

### ゲームの流れとイベント
- ディベートと同じく、状態の真実は追記専用のイベントログにする
- 追加したイベント(`domain/events.py`)
  - `TrialStarted`
  - `TestimonyStarted`
  - `TrialChoicesPrepared`
  - `TrialChoiceMade`
  - `WitnessResponded`
  - `ContradictionSolved`
  - `AnswerSubmitted`
  - `TrialFinished`
  - `ExplanationObjected`
- `PenaltyApplied` / `SessionAborted` / `LLMCallRecorded` は再利用した
- `TrialStarted` には事件の全体(`Case`)を含める。状態をログだけで再構築でき、事件ファイルを後から直しても遊んだ裁判は変わらない
- 状態は `TrialState.from_events` で再構築する(`engine/trial_state.py`)
  - 場面(`stage`)は次のいずれか: examining / choosing / responding / answering / finished
  - 手順違反は `InvalidEventError` にする
  - `DebateState` は裁判のイベントを拒否する(混在を防ぐ)
- 進行: 証言ごとに尋問する。その証言の矛盾をすべて解いたら次の証言へ進み、全矛盾を解いたら最後の問いに答えて閉廷する
- 閉廷の結果(`TrialResult`)
  - `solved`: 正答
  - `wrong_answer`: 誤答
  - `penalty`: ゲージが尽きた
  - どの結果でも解説へ進める

### 分析官は規則で選択肢を組み立てる(`agents/trial_analyst.py`)
- 裁判型では正解(矛盾)と罠が事件のデータで既知なので、LLM を使わない
- 選択肢の構成
  - 正解の組(行 × 証拠品): strong
  - 罠の組: trap(減点 2)
  - はずれの組: weak(減点 1)。`distractor_options` 件
  - ゆさぶる: 減点なし。`probe_options` 件
- 選んだ行動は二度並べない
- 並び順は「セッション ID と手番」を seed に混ぜる(再現可能)
- PLAN では analyst が罠を生成するとしていた。罠は Phase 8 の事件生成で作っているので、Phase 9 の analyst は選ぶだけにした

### 証人(`agents/witness.py`、`prompts/witness/respond.j2`)
- プロンプトに渡すもの
  - 台本: 人物像・隠している事実・守っている嘘
  - 証言
  - 直近のやりとり
  - プレイヤーの行動と「応じ方」の指示
- 応じ方
  - ゆさぶる: 言い逃れる
  - はずれ・罠: 反論する
  - 正解: 台本の反応で崩れる
- 崩れるべきかはコードが決め(正解の組か)、LLM には演技だけをさせる
- 証言の行はプレイヤーに事件のデータのまま見せる(LLM で言い換えない)。矛盾の対応が崩れないようにするため
- 応答はストリーミングする(SSE の `witness` / `token`)

### 台本からの逸脱の検査(`agents/deviation.py`、`prompts/judge/witness_deviation.j2`)
- 応答のたびに judge 役が判定し、`WitnessResponded.check` に記録する(`TrialMode.check_deviations` で無効にできる)
- LLM には事実だけを判定させる
  - 自白したか
  - どの隠している事実を明かしたか
- それぞれ応答からの一字一句の引用を付けさせる。`verify_quote` で応答の中にある引用だけを採用する
  - 引用なしの判定だと、低い推論の判定役が「言い逃れ」を自白と誤判定することが多かった
  - Phase 8 の概要の漏れの検査と同じ方式
- 判定役には公開済みの証言も渡し、証言の繰り返しを漏洩にしないよう指示する
- 逸脱かどうかはコードで決める(`deviations_of`)
  - 崩れるべきでない場面での自白 → `premature_confession`
  - 崩れるべき場面で自白しない → `failed_collapse`
  - 崩れるべきでない場面での漏洩 → `leak`
- 判定に失敗しても進行は止めない(`check=None`。失敗は LLM 呼び出しの記録に残る)

### 解説はデータから組み立てる(`engine/explanation.py`)
- LLM に書かせないのは、出典のない説明を混ぜないため
- 組み立てに使う事件のデータ
  - 真相の要約
  - 問いの答え
  - 矛盾ごとの説明
  - 学習ポイント(知識・出典の URL と引用・古い知識なら以前の通説)
  - 罠と「なぜ選びたくなるか」(学習ポイントのよくある誤解を含む)
- 「解説に異議あり」は、項目を指定してコメントを送ると `ExplanationObjected` として記録する(閉廷後のみ)
  - 項目: 学習ポイント・矛盾・罠
  - 罠の ID は `矛盾の ID/証拠品の ID`

### API(`api/trial_routes.py`)
- エンドポイント
  - `GET /api/cases`: 公開の要約。既定は解けると判定された事件だけ、`?all=true` で全件
  - `POST /api/trials`
  - `GET /api/trials/{id}`: `TrialView`
  - `POST /api/trials/{id}/advance`
  - `POST /api/trials/{id}/choices`: 202。証人の応答はバックグラウンドのタスク
  - `POST /api/trials/{id}/answer`
  - `POST /api/trials/{id}/objections`
- イベントログと SSE はディベートと共通のもの(`/api/sessions/{id}/events`・`/stream`)を使う。`trial_finished` で SSE を閉じる
- ディベートのエンドポイント(一覧・取得・記録・サマリ)は、裁判のセッションを扱わない
- 閉廷までの秘匿(`redact_trial_events`)
  - `TrialStarted` の事件: 学習ポイント・真相・台本・矛盾・正解・`lie_id` を空にする
  - 並べた選択肢の強さ: 過去の分も伏せる。選ばれなかった正解の組が、次の尋問で再び並ぶため
  - LLM 呼び出しの入出力: 台本と真相を含むため伏せる
  - `TrialView` の逸脱の判定: 伏せる
  - 選んだ選択肢の強さは公開する(減点の理由がわかるように)
  - 閉廷後(中断を含む)はすべて公開し、思考ログとして見られる

### CLI と評価
- `llm-court trial <case_id> [--reveal] [--resume ID]`: 検証用の簡易プレイ
- `llm-court eval-trial <case_id...> [--runs N]`: 決まった方針の自動プレイヤーで遊び、逸脱率を測る
  - 自動プレイヤーは、証言ごとに ゆさぶる(全行)→ はずれ 1 回 → 罠 1 回 → 正解 の順に選ぶ
  - ゲージは尽きないように大きくする
  - 指標
    - 自白の早すぎ率
    - 崩れ損ね率
    - 漏洩率
    - 全体の逸脱率
    - 証人の応答時間
  - 指標は全体・事件ごと・行動ごとに集計する
  - 出力は `responses.csv` / `summary.csv` / `report.md`

### フロントエンド
- タイトルに「裁判(事件を解く)」モードを追加し、事件の一覧から開廷する
- `/trial/?session=<id>` の画面
  - 証人の立ち絵(オリジナルの仮素材 `witness.svg`)
  - 証言の行ごとの選択肢
  - 証人の応答のタイプライター表示
  - カットイン
    - つきつける: 「反証!」
    - ゆさぶる: 「確認!」
    - 証言が崩れた: 「証言崩壊!」(強い演出)
  - ゲージ
  - 最後の問い
  - 解説と異議ありのフォーム
  - 閉廷後の尋問の記録(逸脱の判定付き)と思考ログ

## 理由

- 正解が既知の裁判型では、LLM の仕事を演技(証人)と判定(逸脱)に絞り、ゲームの判定(正誤・減点・崩れるべきか)はコードで決める。結果が安定し、再現できる
- 逸脱の判定に引用の検証を課すと、判定役の思い込みによる誤検出を減らせる
- 事件をイベントに含めると、状態をログだけで再構築するという不変条件を保てる。秘匿は API の出力で行い、ストアには完全な形で残す(ディベートの秘匿と同じ方針)

## 影響

- 逸脱率は判定役(judge 役)の質に依存する。低い推論のモデルでは誤判定が残るので、レポートの「逸脱した応答」を目で確認する
- 証人の即興は gpt-oss-20b(reasoning low)でも成立した。一方で、ゆさぶりへの応答で別の理由(入力ミスなど)を作り出し、実質的に誤りを認めることがある
- `TrialMode` に次を追加した。ディベートの `DebateMode` とは別に持つ
  - ゲージ・減点
  - 選択肢の数
  - 逸脱の検査の有無
