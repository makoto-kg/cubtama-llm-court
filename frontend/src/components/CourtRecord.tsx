"use client";

import { useState } from "react";

import type { TrialView } from "@/api/client";
import { STRENGTH_LABELS } from "@/lib/labels";
import { personName } from "@/lib/trial";

type Tab = "people" | "overview" | "log";

const TABS: { id: Tab; label: string }[] = [
  { id: "people", label: "人物" },
  { id: "overview", label: "概要" },
  { id: "log", label: "記録" },
];

/** 法廷記録(人物・事件の概要・尋問の記録)。画面の右から出す。証拠品は `EvidenceOverlay`。 */
export function CourtRecordDrawer({
  view,
  open,
  onClose,
  logNotice,
}: {
  view: TrialView;
  open: boolean;
  onClose: () => void;
  logNotice?: string;
}) {
  const [tab, setTab] = useState<Tab>("people");
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/50" onClick={onClose}>
      <aside
        className="flex h-full w-full max-w-lg flex-col bg-[#241a12] shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex flex-none items-center justify-between px-4 pt-4">
          <h2 className="text-lg font-bold">法廷記録</h2>
          <button onClick={onClose} className="rounded border px-3 py-1 text-sm">
            閉じる
          </button>
        </div>
        <div className="flex flex-none gap-1 border-b border-[var(--court-wood-light)] px-4 pt-3">
          {TABS.map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`rounded-t px-3 py-1.5 text-sm ${
                tab === t.id ? "bg-[var(--court-accent)] font-bold text-black" : "bg-black/30"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-4">
          {tab === "people" && (
            <ul className="space-y-2 text-sm">
              {view.case.people.map((p) => (
                <li key={p.id} className="rounded bg-black/20 p-2">
                  <span className="font-bold">{p.name}</span>({p.role})
                  <p className="opacity-80">{p.description}</p>
                </li>
              ))}
            </ul>
          )}
          {tab === "overview" && (
            <div className="space-y-2 text-sm">
              <p className="font-bold">{view.case.title}</p>
              <p>{view.case.overview}</p>
            </div>
          )}
          {tab === "log" && (
            <div className="space-y-3">
              <ExchangeLog view={view} reveal={false} />
              {logNotice && <p className="rounded bg-black/20 p-2 text-xs opacity-70">{logNotice}</p>}
            </div>
          )}
        </div>
      </aside>
    </div>
  );
}

/** 尋問の記録。閉廷後は台本からの逸脱の判定も表示する。 */
export function ExchangeLog({ view, reveal }: { view: TrialView; reveal: boolean }) {
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
            <p>
              {personName(view, x.witness_id)}: {x.text}
            </p>
            {reveal && x.check && (
              <p className={`mt-1 text-xs ${x.check.deviations.length ? "text-red-300" : "text-emerald-300"}`}>
                台本の判定: {x.check.deviations.length ? x.check.deviations.join(", ") : "逸脱なし"} —{" "}
                {x.check.reason}
              </p>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
