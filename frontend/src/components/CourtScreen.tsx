"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import { useCourtSession } from "@/hooks/useCourtSession";
import { llmCalls } from "@/lib/events";
import { ISSUE_LABELS, phaseTitle, SIDE_LABELS } from "@/lib/labels";
import { turnId } from "@/lib/stream";
import { useCourtStore } from "@/store/court";

import { ChoicePanel } from "./ChoicePanel";
import { CutIn } from "./CutIn";
import { EvidenceDrawer } from "./EvidenceDrawer";
import { Investigation } from "./Investigation";
import { PenaltyGauge } from "./PenaltyGauge";
import { Stage } from "./Stage";
import { ThinkingLog } from "./ThinkingLog";
import { Typewriter } from "./Typewriter";
import { Verdict } from "./Verdict";

/** ゲーム本体。状態に応じて捜査 → 法廷 → 判決を切り替える。 */
export function CourtScreen() {
  const sessionId = useSearchParams().get("session");
  const actions = useCourtSession(sessionId);
  const { view, events, progress, streaming, task, error } = useCourtStore();
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  const [logOpen, setLogOpen] = useState(true);
  const autoRunKey = useRef<string | null>(null);

  const calls = useMemo(() => llmCalls(events), [events]);
  const running = Boolean(view?.running_task) || task?.status === "started";
  const pendingKey = view ? `${view.statements.length}-${view.choices.length}-${view.status}` : "";

  // 対戦では、LLM 側の手番は自動で進める(人間の手番で止まる)
  useEffect(() => {
    if (!view || !view.human_side || running) return;
    if (view.status !== "ready" && view.status !== "in_progress") return;
    if (!view.next_turn || view.next_turn.by_human || view.pending_choices) return;
    if (autoRunKey.current === pendingKey) return;
    autoRunKey.current = pendingKey;
    void actions.run();
  }, [view, running, pendingKey, actions]);

  if (!sessionId) {
    return (
      <p>
        セッションが指定されていません。<Link href="/">タイトルへ</Link>
      </p>
    );
  }
  if (!view) return <p>{error ?? "読み込み中…"}</p>;

  const finished = view.status === "finished" || view.status === "aborted";
  const last = view.statements.at(-1) ?? null;
  const speaking = streaming ?? last;
  const judging = running && view.next_turn?.kind === "verdict";
  const speaker = judging ? "judge" : (speaking?.side ?? null);
  const textKey = speaking ? turnId(speaking) : "none";
  const issues = last ? view.citation_issues.filter((i) => i.statement_id === last.id) : [];
  const phase = view.phase ? phaseTitle(view.phase, view.round) : "開廷前";

  return (
    <div className="space-y-4">
      <CutIn />
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-xs opacity-70">論題</p>
          <h1 className="text-xl font-bold">{view.topic}</h1>
        </div>
        <div className="flex items-center gap-3">
          {view.human_side && <PenaltyGauge remaining={view.penalty_gauge} max={view.penalty_gauge_max} />}
          <button onClick={() => setEvidenceOpen(true)} className="rounded border px-3 py-1 text-sm">
            証拠品ファイル({view.evidence.length})
          </button>
          <button onClick={() => setLogOpen((o) => !o)} className="rounded border px-3 py-1 text-sm">
            思考ログ{logOpen ? "を隠す" : "を表示"}
          </button>
        </div>
      </div>
      {error && <p className="rounded bg-red-900/40 p-2 text-sm">{error}</p>}

      <div className={`grid gap-4 ${logOpen ? "lg:grid-cols-[3fr_2fr]" : ""}`}>
        <div className="space-y-4">
          {view.status === "awaiting_evidence" ? (
            <Investigation progress={progress} running={running} onStart={() => void actions.research()} />
          ) : finished ? (
            <Verdict view={view} />
          ) : (
            <>
              <div>
                <p className="mb-1 text-center text-sm tracking-widest text-[var(--court-accent)]">— {phase} —</p>
                <Stage speaker={speaker} humanSide={view.human_side ?? null} />
                <div className="min-h-40 rounded-b-lg border-t-4 border-[var(--court-accent)] bg-black/70 p-4">
                  <p className="mb-1 font-bold text-[var(--court-accent)]">
                    {judging
                      ? "裁判長"
                      : speaking
                        ? `${SIDE_LABELS[speaking.side]}${speaking.side === view.human_side ? "(あなた)" : ""}`
                        : "裁判長"}
                  </p>
                  <p className="leading-relaxed">
                    {judging ? (
                      <span className="animate-pulse">評議中です…</span>
                    ) : speaking ? (
                      <Typewriter text={speaking.text} resetKey={textKey} active={Boolean(streaming)} />
                    ) : (
                      "これより開廷します。"
                    )}
                  </p>
                  {!streaming && issues.length > 0 && (
                    <ul className="mt-2 text-xs text-amber-300">
                      {issues.map((issue, i) => (
                        <li key={i}>
                          ⚠ {ISSUE_LABELS[issue.kind] ?? issue.kind}: {issue.detail}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </div>

              {view.pending_choices && !running ? (
                <ChoicePanel
                  options={view.pending_choices.options}
                  disabled={running}
                  onChoose={(id) => void actions.choose(id)}
                />
              ) : !view.human_side ? (
                <div className="flex gap-2">
                  <button
                    onClick={() => void actions.advance()}
                    disabled={running}
                    className="rounded bg-[var(--court-accent)] px-4 py-1 font-bold text-black disabled:opacity-50"
                  >
                    次へ
                  </button>
                  <button
                    onClick={() => void actions.run()}
                    disabled={running}
                    className="rounded border px-4 py-1 disabled:opacity-50"
                  >
                    判決まで自動で進める
                  </button>
                  {running && <span className="self-center text-sm opacity-70">進行中…</span>}
                </div>
              ) : (
                <p className="text-sm opacity-70">{running ? "相手の番です…" : ""}</p>
              )}
            </>
          )}
        </div>
        {logOpen && <ThinkingLog calls={calls} />}
      </div>

      <EvidenceDrawer evidence={view.evidence} open={evidenceOpen} onClose={() => setEvidenceOpen(false)} />
    </div>
  );
}
