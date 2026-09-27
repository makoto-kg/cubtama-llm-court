"use client";

import Image from "next/image";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import type { LLMCallInfo, ObjectionTarget, TrialOption, TrialView } from "@/api/client";
import { ASSETS } from "@/assets/manifest";
import { useTrialSession } from "@/hooks/useTrialSession";
import { llmCalls } from "@/lib/events";
import { STRENGTH_LABELS } from "@/lib/labels";
import { currentTestimony, optionsByLine, personName, type WitnessStream } from "@/lib/trial";
import { useTrialStore } from "@/store/trial";

import { CutInView } from "./CutIn";
import { PenaltyGauge } from "./PenaltyGauge";
import { ThinkingLog } from "./ThinkingLog";
import { TrialExplanation } from "./TrialExplanation";
import { Typewriter } from "./Typewriter";

function CaseEvidenceDrawer({ view, open, onClose }: { view: TrialView; open: boolean; onClose: () => void }) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/50" onClick={onClose}>
      <aside
        className="h-full w-full max-w-lg overflow-y-auto bg-[#241a12] p-4 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-bold">証拠品ファイル({view.case.evidence.length})</h2>
          <button onClick={onClose} className="rounded border px-2 text-sm">
            閉じる
          </button>
        </div>
        <ul className="space-y-3">
          {view.case.evidence.map((e) => (
            <li key={e.id} className="rounded border border-[var(--court-wood-light)] p-3">
              <p className="font-bold">{e.name}</p>
              <p className="text-sm opacity-80">{e.description}</p>
              <ul className="mt-1 list-disc pl-5 text-sm">
                {e.details.map((d, i) => (
                  <li key={i}>{d}</li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
        <h2 className="mb-2 mt-5 text-lg font-bold">登場人物</h2>
        <ul className="space-y-2 text-sm">
          {view.case.people.map((p) => (
            <li key={p.id}>
              <span className="font-bold">{p.name}</span>({p.role}): {p.description}
            </li>
          ))}
        </ul>
      </aside>
    </div>
  );
}

function OptionButton({
  option,
  evidenceName,
  disabled,
  onChoose,
}: {
  option: TrialOption;
  evidenceName: string | null;
  disabled: boolean;
  onChoose: (id: string) => void;
}) {
  const present = option.kind === "present";
  return (
    <button
      disabled={disabled}
      onClick={() => onChoose(option.id)}
      className={`rounded border-l-4 bg-black/30 px-3 py-1 text-left text-sm hover:bg-white/10 disabled:opacity-50 ${
        present ? "border-red-400/70" : "border-sky-400/70"
      }`}
    >
      <span className="mr-2 rounded bg-white/10 px-1 text-xs">{present ? "つきつける" : "ゆさぶる"}</span>
      {present ? evidenceName : "詳しく説明させる"}
    </button>
  );
}

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
};

/** 裁判の画面の表示(オンライン・オフライン共通)。データの取得と操作は props で受け取る。 */
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
}: TrialBoardProps) {
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  const finished = view.status === "finished" || view.status === "aborted";
  const testimony = currentTestimony(view);
  const last = view.exchanges.at(-1) ?? null;
  const witnessId = streaming?.witnessId ?? testimony?.witness_id ?? last?.witness_id ?? null;
  const witnessName = witnessId ? personName(view, witnessId) : "証人";
  // 次の証言(別の証人)に移ったら、前の証人の応答は出さない
  const lastForWitness = last && last.witness_id === witnessId ? last : null;
  const evidenceNames = new Map(view.case.evidence.map((e) => [e.id, e.name]));
  const solved = new Set(view.solved_line_ids);
  const chosenLine = last?.option.line_id;
  const lineIds = testimony?.lines.map((l) => l.id) ?? [];
  const groups = optionsByLine(lineIds, view.pending_options);
  const speaking =
    streaming ?? (lastForWitness ? { witnessId: lastForWitness.witness_id, text: lastForWitness.text } : null);
  const textKey = streaming ? `s-${view.exchanges.length}` : `e-${view.exchanges.length}`;

  return (
    <div className="space-y-4">
      <CutInView cutIn={cutIn} onDone={onClearCutIn} />
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-xs opacity-70">事件</p>
          <h1 className="text-xl font-bold">{view.case.title}</h1>
        </div>
        <div className="flex items-center gap-3">
          <PenaltyGauge remaining={view.penalty_gauge} max={view.penalty_gauge_max} />
          <span className="text-sm">
            矛盾 {view.solved_count}/{view.contradiction_count}
          </span>
          <button onClick={() => setEvidenceOpen(true)} className="rounded border px-3 py-1 text-sm">
            証拠品ファイル({view.case.evidence.length})
          </button>
        </div>
      </div>
      {error && <p className="rounded bg-red-900/40 p-2 text-sm">{error}</p>}
      {view.aborted && <p className="rounded bg-red-900/40 p-2 text-sm">中断: {view.aborted}</p>}

      {finished ? (
        <div className="grid gap-4 lg:grid-cols-[3fr_2fr]">
          <TrialExplanation view={view} onObject={onObject} />
          <div className="space-y-4">
            <ExchangeLog view={view} reveal />
            <ThinkingLog calls={calls} />
          </div>
        </div>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[3fr_2fr]">
          <div className="space-y-4">
            <details className="rounded bg-black/20 p-2 text-sm" open={view.exchanges.length === 0}>
              <summary className="cursor-pointer font-bold">事件の概要</summary>
              <p className="mt-1">{view.case.overview}</p>
            </details>

            <div>
              <div className="relative flex h-56 items-end justify-center overflow-hidden rounded-t-lg bg-gradient-to-b from-[#1f2a2a] to-[var(--court-wood)]">
                <Image
                  src={ASSETS.witness}
                  alt={witnessName}
                  width={170}
                  height={221}
                  className={streaming ? "speaking" : ""}
                  priority
                />
              </div>
              <div className="min-h-32 rounded-b-lg border-t-4 border-[var(--court-accent)] bg-black/70 p-4">
                <p className="mb-1 font-bold text-[var(--court-accent)]">{witnessName}</p>
                <p className="leading-relaxed">
                  {speaking ? (
                    <Typewriter text={speaking.text} resetKey={textKey} active={Boolean(streaming)} />
                  ) : (
                    "……(証言台に立っている)"
                  )}
                </p>
                {progress && running && !streaming && (
                  <p className="mt-2 animate-pulse text-xs opacity-70">{progress}</p>
                )}
                {lastForWitness &&
                  !streaming &&
                  lastForWitness.option.strength &&
                  lastForWitness.option.strength !== "strong" && (
                    <p className="mt-2 text-xs text-amber-300">
                      つきつけた組: {STRENGTH_LABELS[lastForWitness.option.strength]}
                      {lastForWitness.penalty > 0 && `(ペナルティ −${lastForWitness.penalty})`}
                    </p>
                  )}
              </div>
            </div>

            {view.stage === "answering" ? (
              <div className="space-y-2 rounded-lg border-2 border-[var(--court-accent)] bg-black/40 p-4">
                <p className="font-bold">すべての矛盾を解きました。最後の問いに答えてください。</p>
                <p className="text-lg">{view.case.question.text}</p>
                <div className="grid gap-2 md:grid-cols-2">
                  {view.case.question.options.map((option, i) => (
                    <button
                      key={i}
                      onClick={() => onAnswer(i)}
                      disabled={running}
                      className="rounded bg-black/40 p-3 text-left hover:bg-white/10 disabled:opacity-50"
                    >
                      {i + 1}. {option}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              testimony && (
                <section className="space-y-2 rounded-lg border border-[var(--court-wood-light)] p-3">
                  <h2 className="font-bold">
                    {testimony.title}
                    <span className="ml-2 text-sm font-normal opacity-70">
                      証人: {personName(view, testimony.witness_id)}
                    </span>
                  </h2>
                  {running && <p className="text-sm opacity-70">証人が答えています…</p>}
                  <ol className="space-y-2">
                    {testimony.lines.map((line) => {
                      const group = groups.find((g) => g.lineId === line.id);
                      return (
                        <li
                          key={line.id}
                          className={`rounded p-2 ${line.id === chosenLine ? "bg-white/10" : "bg-black/20"}`}
                        >
                          <p className={solved.has(line.id) ? "text-emerald-300 line-through" : ""}>
                            {solved.has(line.id) ? "✓ " : "「"}
                            {line.text}
                            {solved.has(line.id) ? "" : "」"}
                          </p>
                          {group && !running && (
                            <div className="mt-1 flex flex-wrap gap-2">
                              {group.options.map((o) => (
                                <OptionButton
                                  key={o.id}
                                  option={o}
                                  evidenceName={o.evidence_id ? (evidenceNames.get(o.evidence_id) ?? o.evidence_id) : null}
                                  disabled={running}
                                  onChoose={onChoose}
                                />
                              ))}
                            </div>
                          )}
                        </li>
                      );
                    })}
                  </ol>
                </section>
              )
            )}
          </div>
          <div className="space-y-4">
            <ExchangeLog view={view} reveal={false} />
            <p className="rounded bg-black/20 p-2 text-xs opacity-70">
              {logNotice}
            </p>
          </div>
        </div>
      )}

      <CaseEvidenceDrawer view={view} open={evidenceOpen} onClose={() => setEvidenceOpen(false)} />
    </div>
  );
}

/** 尋問の記録。閉廷後は台本からの逸脱の判定も表示する。 */
function ExchangeLog({ view, reveal }: { view: TrialView; reveal: boolean }) {
  return (
    <section className="rounded-lg border border-[var(--court-wood-light)] bg-black/30 p-3">
      <h2 className="mb-2 font-bold">尋問の記録</h2>
      {view.exchanges.length === 0 && <p className="text-sm opacity-70">まだありません</p>}
      <ul className="max-h-[28rem] space-y-2 overflow-y-auto text-sm">
        {[...view.exchanges].reverse().map((x) => (
          <li key={x.option.id} className="rounded bg-black/20 p-2">
            <p className="text-xs opacity-80">
              {x.option.label}
              {x.option.strength && ` — ${STRENGTH_LABELS[x.option.strength]}`}
              {x.solved && " — 証言が崩れた"}
            </p>
            <p>{personName(view, x.witness_id)}: {x.text}</p>
            {reveal && x.check && (
              <p className={`mt-1 text-xs ${x.check.deviations.length ? "text-red-300" : "text-emerald-300"}`}>
                台本の判定: {x.check.deviations.length ? x.check.deviations.join(", ") : "逸脱なし"} — {x.check.reason}
              </p>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
