"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";

import type { LLMCallInfo, ObjectionTarget, TrialOption, TrialView } from "@/api/client";
import { TRIAL_ROLE_NAMES } from "@/assets/manifest";
import { useTrialSession } from "@/hooks/useTrialSession";
import { llmCalls } from "@/lib/events";
import { isAdvanceKey } from "@/lib/keys";
import { STRENGTH_LABELS } from "@/lib/labels";
import { shouldShowOpening } from "@/lib/opening";
import { defendantPose, prosecutorPose } from "@/lib/pose";
import { judgeLabel, prosecutorLabel, speakerLabel } from "@/lib/roles";
import { endingScene } from "@/lib/verdict";
import {
  COLLAPSE_CUT_IN,
  currentTestimony,
  focusLine,
  optionsByLine,
  pendingCollapse,
  personName,
  prosecutorLine,
  shownPenaltyGauge,
  stepLine,
  testimonyExamined,
  type WitnessStream,
} from "@/lib/trial";
import { useTrialStore } from "@/store/trial";

import { CourtRecordDrawer, ExchangeLog } from "./CourtRecord";
import { CourtShot, DialogueBox } from "./CourtScene";
import { CutInView } from "./CutIn";
import { EvidenceOverlay, NewEvidenceNotice } from "./EvidenceOverlay";
import { ExaminationPanel } from "./ExaminationPanel";
import { GameShell } from "./GameShell";
import { OpeningSequence, SuspensionSequence, VerdictSequence } from "./OpeningSequence";
import { PenaltyGauge } from "./PenaltyGauge";
import { TestimonyRecital } from "./TestimonyRecital";
import { ThinkingLog } from "./ThinkingLog";
import { TrialExplanation } from "./TrialExplanation";
import { Typewriter } from "./Typewriter";

/** 裁判型の画面。被告の証言 → 検察官の尋問(選択肢)→ 被告の応答 → 最後の問い → 解説。 */
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
  // 「証言崩壊!」は、崩れた応答を読み終えてから出す。見せ終えた応答の番号と、読み終えた応答のキー
  // (開いた時点までの応答は見せ終えたことにする。読み直しで同じ演出を繰り返さない)
  const [collapseShown, setCollapseShown] = useState(() => view.exchanges.length - 1);
  const [typedKey, setTypedKey] = useState<string | null>(null);
  // 「ゆさぶる」「つきつける」を選んだら、被告が答える前に検察官(プレイヤー)の台詞を出す。
  // index は選んだときの応答の数(= この行動への応答の番号)。この画面で選んだ行動だけ(読み直しでは出さない)。
  // gauge は選ぶ前のゲージ(応答を読み終えるまでは、この値を見せる)
  const [accusation, setAccusation] = useState<{
    option: TrialOption;
    index: number;
    spoken: boolean;
    gauge: number;
  } | null>(null);
  const [accusationTyped, setAccusationTyped] = useState<number | null>(null);
  // 尋問の中で手に入った証拠品の知らせ(ADR 0019)。知らせ終えた証拠品(開いた時点で手元にあるものは知らせない)
  const [knownEvidence, setKnownEvidence] = useState(() => view.case.evidence.map((e) => e.id));
  // 閉廷したら、最後の応答を読んでから結末の場面へ。全矛盾を解いたら判決(ADR 0020)、
  // ゲージが尽きたら審理の中断(ADR 0022)。開いた時点で閉廷していた裁判では出さず、裁判のまとめだけにする
  const [endingDone, setEndingDone] = useState(() => view.status === "finished" || view.status === "aborted");
  const [endingStarted, setEndingStarted] = useState(false);
  const finished = view.status === "finished" || view.status === "aborted";
  const ending = endingDone ? null : endingScene(view);
  const endingPending = ending !== null;
  const testimony = currentTestimony(view);
  // 証言が始まったら、まず被告に一通り証言させてから尋問の操作を出す。
  // 被告の応答・カットインの最中は待ち、前の応答が画面にあればタップで次の証言へ進める
  const recitalNeeded = Boolean(testimony) && view.stage !== "answering" && heardId !== testimony?.id;
  const prosecutorPhase = accusation !== null && !accusation.spoken;
  const quiet = !streaming && !cutIn && !prosecutorPhase;
  const recitalPlaying =
    recitalNeeded && quiet && (playId === testimony?.id || view.exchanges.length === 0);
  const recitalPending = recitalNeeded && quiet && !recitalPlaying;
  const last = view.exchanges.at(-1) ?? null;
  const witnessId = streaming?.witnessId ?? testimony?.witness_id ?? last?.witness_id ?? null;
  const witnessName = witnessId ? speakerLabel(view, witnessId) : TRIAL_ROLE_NAMES.defendant;
  const solved = new Set(view.solved_line_ids);
  const lineIds = testimony?.lines.map((l) => l.id) ?? [];
  const groups = optionsByLine(lineIds, view.pending_options);
  const lineId = focusLine(lineIds, groups, lineChoice);
  const line = testimony?.lines.find((l) => l.id === lineId) ?? null;
  // 台詞の枠: 被告の応答(ストリーミング中、または行を指し直す前の最新の応答)か、指している証言の行
  const replyFromLast = !streaming && last && (lineAt === null || lineAt < view.exchanges.length) ? last : null;
  const reply =
    streaming ?? (replyFromLast ? { witnessId: replyFromLast.witness_id, text: replyFromLast.text } : null);
  // 応答ごとに同じキーにする(ストリーミングが終わって記録に移っても打ち直さない)
  const replyKey = `r-${streaming ? view.exchanges.length : view.exchanges.length - 1}`;
  // カットイン(確認!・反証!・証言崩壊! など)と検察官の台詞が終わるまで、応答の台詞は送らない
  const holdReply = Boolean(cutIn) || prosecutorPhase;
  const markTyped = useCallback(() => setTypedKey(replyKey), [replyKey]);
  // 応答の台詞を打ち出している間は被告が話している(口パク)。ストリーミングが終わっても、打ち終えるまで続ける
  const replyTyping = !holdReply && typedKey !== replyKey;
  const replyText = (text: string) => (
    <Typewriter
      text={text}
      resetKey={replyKey}
      active={Boolean(streaming)}
      paused={holdReply}
      onDone={markTyped}
    />
  );
  const collapseIndex = streaming || prosecutorPhase ? null : pendingCollapse(view.exchanges, collapseShown);
  // 崩れた応答を読み終えるまで、次の操作に進ませない
  const collapseBusy = collapseIndex !== null;
  const collapseCutIn = useMemo(
    () =>
      collapseIndex !== null && !cutIn && typedKey === `r-${collapseIndex}`
        ? { text: COLLAPSE_CUT_IN, key: -1 - collapseIndex, strong: true }
        : null,
    [collapseIndex, cutIn, typedKey],
  );
  // 新しい証拠品は、手に入れた応答を読み終えてから知らせる(カットイン・証言崩壊の後)
  const newEvidence = view.case.evidence.filter((e) => !knownEvidence.includes(e.id));
  const evidenceBusy = newEvidence.length > 0;
  const showNewEvidence =
    evidenceBusy &&
    !streaming &&
    !prosecutorPhase &&
    !cutIn &&
    !collapseCutIn &&
    !collapseBusy &&
    typedKey === `r-${view.exchanges.length - 1}`;
  const clearCollapse = useCallback(() => {
    if (collapseIndex !== null) setCollapseShown(collapseIndex);
  }, [collapseIndex]);
  const choose = (optionId: string) => {
    const option = view.pending_options.find((o) => o.id === optionId);
    if (option) setAccusation({ option, index: view.exchanges.length, spoken: false, gauge: view.penalty_gauge });
    onChoose(optionId);
  };
  const finishAccusation = useCallback(
    () => setAccusation((a) => (a && !a.spoken ? { ...a, spoken: true } : a)),
    [],
  );
  // 検察官の台詞は、読み終えてからタップ・Enter・Space で被告の応答へ進む(自動では進めない)
  const accusationReady = prosecutorPhase && !cutIn && accusationTyped === accusation?.index;
  useEffect(() => {
    if (!accusationReady) return;
    const onKey = (e: KeyboardEvent) => {
      if (isAdvanceKey(e)) {
        e.preventDefault();
        finishAccusation();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [accusationReady, finishAccusation]);
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
      gauge={shownPenaltyGauge(view.penalty_gauge, accusation, typedKey)}
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
            ? { lineText: line.text, options: presentOptions, onPresent: choose }
            : null
        }
      />
    </>
  );

  if (!openingDone && !finished) {
    return <OpeningSequence view={view} onFinish={() => setOpeningDone(true)} />;
  }

  if (ending && endingStarted) {
    const Sequence = ending === "verdict" ? VerdictSequence : SuspensionSequence;
    return <Sequence view={view} onFinish={() => setEndingDone(true)} />;
  }

  if (finished && !endingPending) {
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

  const examination = (busy: boolean) =>
    testimony && (
      <ExaminationPanel
        key={lineId ?? ""}
        testimony={testimony}
        lineId={lineId}
        options={view.pending_options.filter((o) => o.line_id === lineId)}
        solved={solved}
        running={busy}
        onLine={pointLine}
        onChoose={choose}
        onPresent={() => setEvidence({ present: true })}
        onReplay={() => {
          setHeardId(null);
          setPlayId(testimony.id);
        }}
      />
    );

  let stage: ReactNode;
  let panel: ReactNode = null;
  if (prosecutorPhase && accusation) {
    const option = accusation.option;
    const lineText =
      view.case.testimonies.flatMap((t) => t.lines).find((l) => l.id === option.line_id)?.text ?? "";
    const evidenceName = view.case.evidence.find((e) => e.id === option.evidence_id)?.name ?? null;
    const typed = accusationTyped === accusation.index;
    stage = (
      <CourtShot
        kind="prosecutor"
        alt={TRIAL_ROLE_NAMES.prosecutor}
        pose={prosecutorPose(option)}
        speaking={!cutIn && !typed}
      >
        <DialogueBox
          name={prosecutorLabel(view)}
          waiting={typed && !cutIn}
          onClick={typed && !cutIn ? finishAccusation : undefined}
        >
          <p>
            <Typewriter
              text={prosecutorLine(option, lineText, evidenceName, accusation.index, view.case.prosecutor_speech)}
              resetKey={`p-${accusation.index}`}
              active={false}
              paused={Boolean(cutIn)}
              onDone={() => setAccusationTyped(accusation.index)}
            />
          </p>
        </DialogueBox>
      </CourtShot>
    );
    panel = examination(true);
  } else if (endingPending && last) {
    // 最後の矛盾を崩した応答(と「証言崩壊!」)のあと判決へ。ゲージが尽きた応答のあとは審理の中断へ
    const waiting = Boolean(streaming) || holdReply || collapseBusy;
    stage = (
      <CourtShot
        kind="stand"
        alt={personName(view, last.witness_id)}
        pose={defendantPose(last.option)}
        speaking={replyTyping}
      >
        <DialogueBox
          name={speakerLabel(view, last.witness_id)}
          waiting={!waiting}
          onClick={waiting ? undefined : () => setEndingStarted(true)}
        >
          <p>{replyText(last.text)}</p>
        </DialogueBox>
      </CourtShot>
    );
    panel = (
      <button
        onClick={() => setEndingStarted(true)}
        disabled={waiting}
        className="w-full rounded-lg border-2 border-[var(--court-accent)] bg-black/40 p-3 font-bold hover:bg-white/10 disabled:opacity-40"
      >
        {ending === "verdict" ? "判決へ ▶" : "次へ ▶"}
      </button>
    );
  } else if (recitalPlaying && testimony) {
    stage = (
      <TestimonyRecital key={testimony.id} view={view} testimony={testimony} onFinish={() => finishRecital(testimony.id)} />
    );
  } else if (recitalPending && last && testimony) {
    stage = (
      <CourtShot
        kind="stand"
        alt={personName(view, last.witness_id)}
        pose={defendantPose(last.option)}
        speaking={replyTyping}
      >
        <DialogueBox
          name={speakerLabel(view, last.witness_id)}
          waiting={!collapseBusy}
          onClick={collapseBusy ? undefined : () => setPlayId(testimony.id)}
        >
          <p>{replyText(last.text)}</p>
        </DialogueBox>
      </CourtShot>
    );
    panel = (
      <button
        onClick={() => setPlayId(testimony.id)}
        disabled={collapseBusy}
        className="w-full rounded-lg border-2 border-[var(--court-accent)] bg-black/40 p-3 font-bold hover:bg-white/10 disabled:opacity-40"
      >
        次の証言を聞く ▶
      </button>
    );
  } else if (view.stage === "answering" && !questionReady && last && !streaming) {
    stage = (
      <CourtShot
        kind="stand"
        alt={personName(view, last.witness_id)}
        pose={defendantPose(last.option)}
        speaking={replyTyping}
      >
        <DialogueBox
          name={speakerLabel(view, last.witness_id)}
          waiting={!holdReply && !collapseBusy}
          onClick={holdReply || collapseBusy ? undefined : () => setQuestionReady(true)}
        >
          <p>{replyText(last.text)}</p>
        </DialogueBox>
      </CourtShot>
    );
    panel = (
      <button
        onClick={() => setQuestionReady(true)}
        disabled={holdReply || collapseBusy}
        className="w-full rounded-lg border-2 border-[var(--court-accent)] bg-black/40 p-3 font-bold hover:bg-white/10 disabled:opacity-40"
      >
        最後の問いへ ▶
      </button>
    );
  } else if (view.stage === "answering" && !streaming) {
    stage = (
      <CourtShot kind="judge" alt={judgeLabel()}>
        <DialogueBox name={judgeLabel()}>
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
    const busy = Boolean(streaming) || running || holdReply || collapseBusy || evidenceBusy;
    const speakerName = reply ? speakerLabel(view, reply.witnessId) : witnessName;
    // 応答中は選んだ行動(この画面で選んだものだけ)、応答のあとは記録の行動で表情を決める
    const replyOption = streaming
      ? accusation?.index === view.exchanges.length
        ? accusation.option
        : null
      : (replyFromLast?.option ?? null);
    stage = (
      <CourtShot
        kind="stand"
        alt={speakerName}
        pose={reply ? defendantPose(replyOption) : "standard"}
        speaking={Boolean(reply) && replyTyping}
      >
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
              {/* 組の強さ・ペナルティは、応答を読み終えてから(ゲージが減るのと同時に)見せる */}
              {replyFromLast &&
                !holdReply &&
                typedKey === replyKey &&
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
    panel = examination(busy);
  }

  return (
    <>
      <CutInView cutIn={cutIn} onDone={onClearCutIn} />
      <CutInView cutIn={collapseCutIn} onDone={clearCollapse} />
      {showNewEvidence && (
        <NewEvidenceNotice
          evidence={newEvidence}
          onClose={() => setKnownEvidence(view.case.evidence.map((e) => e.id))}
        />
      )}
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
  gauge,
  toolbar,
  onEvidence,
  onRecord,
}: {
  view: TrialView;
  /** 画面に出すゲージ(`shownPenaltyGauge`)。 */
  gauge: number;
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
        <PenaltyGauge remaining={gauge} max={view.penalty_gauge_max} />
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
