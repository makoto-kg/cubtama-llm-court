"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState, type ReactNode } from "react";

import type { LLMCallInfo, ObjectionTarget, TrialView } from "@/api/client";
import { useTrialSession } from "@/hooks/useTrialSession";
import { llmCalls } from "@/lib/events";
import { STRENGTH_LABELS } from "@/lib/labels";
import { shouldShowOpening } from "@/lib/opening";
import {
  currentTestimony,
  focusLine,
  optionsByLine,
  personName,
  stepLine,
  testimonyExamined,
  type WitnessStream,
} from "@/lib/trial";
import { useTrialStore } from "@/store/trial";

import { CourtRecordDrawer, ExchangeLog } from "./CourtRecord";
import { CourtShot, DialogueBox } from "./CourtScene";
import { CutInView } from "./CutIn";
import { EvidenceOverlay } from "./EvidenceOverlay";
import { ExaminationPanel } from "./ExaminationPanel";
import { GameShell } from "./GameShell";
import { OpeningSequence } from "./OpeningSequence";
import { PenaltyGauge } from "./PenaltyGauge";
import { TestimonyRecital } from "./TestimonyRecital";
import { ThinkingLog } from "./ThinkingLog";
import { TrialExplanation } from "./TrialExplanation";
import { Typewriter } from "./Typewriter";

/** 裁判型の画面。証言 → 尋問(選択肢)→ 証人の応答 → 最後の問い → 解説。 */
export function TrialScreen() {
  const sessionId = useSearchParams().get("session");
  const actions = useTrialSession(sessionId);
  const { view, events, streaming, progress, task, cutIn, error, clearCutIn } = useTrialStore();
  const calls = useMemo(() => llmCalls(events), [events]);
  const running = Boolean(view?.running_task) || task?.status === "started";
  const needsAdvance = view?.stage === "examining" && !running;

  // 選択肢の用意待ち(応答の途中の中断からの回復など)なら自動で用意する
  useEffect(() => {
    if (needsAdvance) void actions.advance();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 状態の変化でだけ動かす
  }, [needsAdvance]);

  if (!sessionId) {
    return (
      <p>
        裁判が指定されていません。<Link href="/">タイトルへ</Link>
      </p>
    );
  }
  if (!view) return <p>{error ?? "読み込み中…"}</p>;
  return (
    <TrialBoard
      view={view}
      streaming={streaming}
      progress={progress}
      running={running}
      error={error}
      cutIn={cutIn}
      onClearCutIn={clearCutIn}
      calls={calls}
      onChoose={(id) => void actions.choose(id)}
      onAnswer={(i) => void actions.answer(i)}
      onObject={actions.object}
      toolbar={
        <Link href="/" className="rounded border px-2 py-0.5">
          タイトルへ
        </Link>
      }
    />
  );
}

export type TrialBoardProps = {
  view: TrialView;
  streaming: WitnessStream | null;
  progress: string | null;
  running: boolean;
  error: string | null;
  cutIn: { text: string; key: number; strong?: boolean } | null;
  onClearCutIn: () => void;
  calls: LLMCallInfo[];
  onChoose: (optionId: string) => void;
  onAnswer: (index: number) => void;
  onObject: (kind: ObjectionTarget, id: string, comment: string) => Promise<void>;
  /** 閉廷前に思考ログの代わりに出す注記。 */
  logNotice?: string;
  /** 画面上端のバーに並べる操作(やり直す・一覧へ など)。 */
  toolbar?: ReactNode;
};

/**
 * 裁判の画面の表示(オンライン・オフライン共通)。データの取得と操作は props で受け取る。
 * スマホの縦画面では、キャラクターと台詞を画面に固定し、下の操作の欄だけを動かす(`GameShell`)。
 */
export function TrialBoard({
  view,
  streaming,
  progress,
  running,
  error,
  cutIn,
  onClearCutIn,
  calls,
  onChoose,
  onAnswer,
  onObject,
  logNotice = "書記官の記録(思考ログ)は、台本と真相を含むため閉廷後に公開します。",
  toolbar,
}: TrialBoardProps) {
  const [recordOpen, setRecordOpen] = useState(false);
  // 証拠品ファイル(法廷の画面に重ねる)。present は「つきつける」から開いたとき
  const [evidence, setEvidence] = useState<{ present: boolean } | null>(null);
  // 開廷の場面は、尋問が始まる前に開いたときだけ見せる(途中から再開した裁判では出さない)
  const [openingDone, setOpeningDone] = useState(() => !shouldShowOpening(view));
  // 読み上げを終えた証言と、読み上げを始めてよい証言(尋問の途中から再開した証言は読み上げない)
  const [heardId, setHeardId] = useState(() => (testimonyExamined(view) ? view.testimony_id : null));
  const [playId, setPlayId] = useState<string | null>(null);
  // 尋問で指している証言の行と、行を指し直したときの応答の数(それより後の応答だけを台詞の枠に出す)
  const [lineChoice, setLineChoice] = useState<string | null>(null);
  const [lineAt, setLineAt] = useState<number | null>(null);
  // 最後の問いに移る前に、証言が崩れた応答を読んでもらう(タップで問いへ)
  const [questionReady, setQuestionReady] = useState(false);
  const finished = view.status === "finished" || view.status === "aborted";
  const testimony = currentTestimony(view);
  // 証言が始まったら、まず証人に一通り証言させてから尋問の操作を出す。
  // 証人の応答・カットインの最中は待ち、前の応答が画面にあればタップで次の証言へ進める
  const recitalNeeded = Boolean(testimony) && view.stage !== "answering" && heardId !== testimony?.id;
  const quiet = !streaming && !cutIn;
  const recitalPlaying =
    recitalNeeded && quiet && (playId === testimony?.id || view.exchanges.length === 0);
  const recitalPending = recitalNeeded && quiet && !recitalPlaying;
  const last = view.exchanges.at(-1) ?? null;
  const witnessId = streaming?.witnessId ?? testimony?.witness_id ?? last?.witness_id ?? null;
  const witnessName = witnessId ? personName(view, witnessId) : "証人";
  const solved = new Set(view.solved_line_ids);
  const lineIds = testimony?.lines.map((l) => l.id) ?? [];
  const groups = optionsByLine(lineIds, view.pending_options);
  const lineId = focusLine(lineIds, groups, lineChoice);
  const line = testimony?.lines.find((l) => l.id === lineId) ?? null;
  // 台詞の枠: 証人の応答(ストリーミング中、または行を指し直す前の最新の応答)か、指している証言の行
  const replyFromLast = !streaming && last && (lineAt === null || lineAt < view.exchanges.length) ? last : null;
  const reply =
    streaming ?? (replyFromLast ? { witnessId: replyFromLast.witness_id, text: replyFromLast.text } : null);
  // 応答ごとに同じキーにする(ストリーミングが終わって記録に移っても打ち直さない)
  const replyKey = `r-${streaming ? view.exchanges.length : view.exchanges.length - 1}`;
  // カットイン(確認!・反証!・証言崩壊! など)が消えるまで、応答の台詞は送らない
  const holdReply = Boolean(cutIn);
  const replyText = (text: string) => (
    <Typewriter text={text} resetKey={replyKey} active={Boolean(streaming)} paused={holdReply} />
  );
  const pointLine = (id: string | null) => {
    if (!id) return;
    setLineChoice(id);
    setLineAt(view.exchanges.length);
  };
  // 証言の読み上げを終えたら、前の証言への応答ではなく証言の行を出す
  const finishRecital = (id: string) => {
    setHeardId(id);
    setLineAt(view.exchanges.length);
  };

  const top = (
    <TopBar
      view={view}
      toolbar={toolbar}
      onEvidence={() => setEvidence({ present: false })}
      onRecord={() => setRecordOpen(true)}
    />
  );
  const presentOptions = view.pending_options.filter((o) => o.line_id === lineId && o.kind === "present");
  const drawer = (
    <>
      <CourtRecordDrawer view={view} open={recordOpen} onClose={() => setRecordOpen(false)} logNotice={logNotice} />
      <EvidenceOverlay
        view={view}
        open={evidence !== null}
        onClose={() => setEvidence(null)}
        present={
          evidence?.present && line && !finished
            ? { lineText: line.text, options: presentOptions, onPresent: onChoose }
            : null
        }
      />
    </>
  );

  if (!openingDone && !finished) {
    return <OpeningSequence view={view} onFinish={() => setOpeningDone(true)} />;
  }

  if (finished) {
    return (
      <div className="space-y-4">
        <CutInView cutIn={cutIn} onDone={onClearCutIn} />
        {top}
        {error && <p className="rounded bg-red-900/40 p-2 text-sm">{error}</p>}
        {view.aborted && <p className="rounded bg-red-900/40 p-2 text-sm">中断: {view.aborted}</p>}
        <div className="grid gap-4 lg:grid-cols-[3fr_2fr]">
          <TrialExplanation view={view} onObject={onObject} />
          <div className="space-y-4">
            <ExchangeLog view={view} reveal />
            <ThinkingLog calls={calls} />
          </div>
        </div>
        {drawer}
      </div>
    );
  }

  let stage: ReactNode;
  let panel: ReactNode = null;
  if (recitalPlaying && testimony) {
    stage = (
      <TestimonyRecital key={testimony.id} view={view} testimony={testimony} onFinish={() => finishRecital(testimony.id)} />
    );
  } else if (recitalPending && last && testimony) {
    stage = (
      <CourtShot kind="witness" alt={personName(view, last.witness_id)}>
        <DialogueBox name={personName(view, last.witness_id)} waiting onClick={() => setPlayId(testimony.id)}>
          <p>{replyText(last.text)}</p>
        </DialogueBox>
      </CourtShot>
    );
    panel = (
      <button
        onClick={() => setPlayId(testimony.id)}
        className="w-full rounded-lg border-2 border-[var(--court-accent)] bg-black/40 p-3 font-bold hover:bg-white/10"
      >
        次の証言を聞く ▶
      </button>
    );
  } else if (view.stage === "answering" && !questionReady && last && !streaming) {
    stage = (
      <CourtShot kind="witness" alt={personName(view, last.witness_id)}>
        <DialogueBox
          name={personName(view, last.witness_id)}
          waiting={!holdReply}
          onClick={holdReply ? undefined : () => setQuestionReady(true)}
        >
          <p>{replyText(last.text)}</p>
        </DialogueBox>
      </CourtShot>
    );
    panel = (
      <button
        onClick={() => setQuestionReady(true)}
        disabled={holdReply}
        className="w-full rounded-lg border-2 border-[var(--court-accent)] bg-black/40 p-3 font-bold hover:bg-white/10 disabled:opacity-40"
      >
        最後の問いへ ▶
      </button>
    );
  } else if (view.stage === "answering" && !streaming) {
    stage = (
      <CourtShot kind="judge" alt="裁判長">
        <DialogueBox name="裁判長">
          <p>
            すべての矛盾が明らかになりました。最後に問います。
            <br />
            <span className="font-bold">{view.case.question.text}</span>
          </p>
        </DialogueBox>
      </CourtShot>
    );
    panel = (
      <div className="grid gap-2 md:grid-cols-2">
        {view.case.question.options.map((option, i) => (
          <button
            key={i}
            onClick={() => onAnswer(i)}
            disabled={running}
            className="rounded-lg border border-[var(--court-accent)]/60 bg-black/40 p-3 text-left hover:bg-white/10 disabled:opacity-50"
          >
            {i + 1}. {option}
          </button>
        ))}
      </div>
    );
  } else {
    const showLine = !reply && line;
    const busy = Boolean(streaming) || running || holdReply;
    const speakerName = reply ? personName(view, reply.witnessId) : witnessName;
    stage = (
      <CourtShot kind="witness" alt={speakerName} speaking={Boolean(streaming) && !holdReply}>
        <DialogueBox
          name={speakerName}
          waiting={!busy}
          onClick={busy ? undefined : () => pointLine(reply ? lineId : stepLine(lineIds, lineId, 1))}
        >
          {reply ? (
            <>
              <p>{replyText(reply.text)}</p>
              {progress && running && !streaming && (
                <p className="mt-1 animate-pulse text-xs opacity-70">{progress}</p>
              )}
              {replyFromLast &&
                !holdReply &&
                replyFromLast.option.strength &&
                replyFromLast.option.strength !== "strong" && (
                  <p className="mt-1 text-xs text-amber-300">
                    つきつけた組: {STRENGTH_LABELS[replyFromLast.option.strength]}
                    {replyFromLast.penalty > 0 && `(ペナルティ −${replyFromLast.penalty})`}
                  </p>
                )}
            </>
          ) : showLine ? (
            <>
              <p className={`testimony-text ${solved.has(showLine.id) ? "line-through opacity-70" : ""}`}>
                「{showLine.text}」
              </p>
              <span className="absolute -top-6 right-1 rounded bg-black/60 px-2 text-xs">
                {lineIds.indexOf(showLine.id) + 1}/{lineIds.length}
              </span>
            </>
          ) : (
            <p>……(証言台に立っている)</p>
          )}
        </DialogueBox>
      </CourtShot>
    );
    panel = testimony && (
      <ExaminationPanel
        key={lineId ?? ""}
        testimony={testimony}
        lineId={lineId}
        options={view.pending_options.filter((o) => o.line_id === lineId)}
        solved={solved}
        running={busy}
        onLine={pointLine}
        onChoose={onChoose}
        onPresent={() => setEvidence({ present: true })}
        onReplay={() => {
          setHeardId(null);
          setPlayId(testimony.id);
        }}
      />
    );
  }

  return (
    <>
      <CutInView cutIn={cutIn} onDone={onClearCutIn} />
      <GameShell
        top={
          <>
            {top}
            {error && <p className="mt-1 rounded bg-red-900/40 p-2 text-xs">{error}</p>}
            {view.aborted && <p className="mt-1 rounded bg-red-900/40 p-2 text-xs">中断: {view.aborted}</p>}
          </>
        }
        stage={stage}
        panel={panel}
        side={
          <>
            <details className="rounded bg-black/20 p-2 text-sm" open={view.exchanges.length === 0}>
              <summary className="cursor-pointer font-bold">事件の概要</summary>
              <p className="mt-1">{view.case.overview}</p>
            </details>
            <ExchangeLog view={view} reveal={false} />
            <p className="rounded bg-black/20 p-2 text-xs opacity-70">{logNotice}</p>
          </>
        }
      />
      {drawer}
    </>
  );
}

/** 画面上端のバー(事件名・操作 / ゲージ・矛盾の数・証拠品・記録)。スマホでも 2 行に収める。 */
function TopBar({
  view,
  toolbar,
  onEvidence,
  onRecord,
}: {
  view: TrialView;
  toolbar?: ReactNode;
  onEvidence: () => void;
  onRecord: () => void;
}) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between gap-2">
        <h1 className="min-w-0 truncate text-sm font-bold lg:text-xl">{view.case.title}</h1>
        {toolbar && <div className="flex shrink-0 items-center gap-1.5 text-xs">{toolbar}</div>}
      </div>
      <div className="flex items-center justify-between gap-2">
        <PenaltyGauge remaining={view.penalty_gauge} max={view.penalty_gauge_max} />
        <span className="text-xs tabular-nums lg:text-sm">
          矛盾 {view.solved_count}/{view.contradiction_count}
        </span>
        <div className="flex gap-1.5">
          <button
            onClick={onEvidence}
            className="rounded bg-[var(--court-accent)] px-2.5 py-1 text-xs font-bold text-black lg:text-sm"
          >
            証拠品({view.case.evidence.length})
          </button>
          <button
            onClick={onRecord}
            className="rounded border border-[var(--court-accent)] px-2.5 py-1 text-xs font-bold text-[var(--court-accent)] lg:text-sm"
          >
            記録
          </button>
        </div>
      </div>
    </div>
  );
}
