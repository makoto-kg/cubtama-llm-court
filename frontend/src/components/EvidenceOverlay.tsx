"use client";

import { useEffect } from "react";

import type { TrialOption, TrialView } from "@/api/client";

/** つきつける場面の情報(指している証言の行と、その行に並んだ「つきつける」の選択肢)。 */
export type PresentTarget = {
  lineText: string;
  options: TrialOption[];
  onPresent: (optionId: string) => void;
};

/**
 * 証拠品ファイル。今の画面(法廷)の上に重ねて出す。
 * `present` を渡すと「つきつける」場面になり、その行に並んだ証拠品に「つきつける」ボタンを出す。
 */
export function EvidenceOverlay({
  view,
  open,
  onClose,
  present,
}: {
  view: TrialView;
  open: boolean;
  onClose: () => void;
  present?: PresentTarget | null;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;
  const presentable = new Map(
    (present?.options ?? []).filter((o) => o.evidence_id).map((o) => [o.evidence_id as string, o.id]),
  );
  return (
    <div
      className="fixed inset-0 z-40 flex items-end justify-center bg-black/55 sm:items-center"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label="証拠品ファイル"
    >
      <div
        className="evidence-sheet flex max-h-[78svh] w-full max-w-lg flex-col rounded-t-2xl border-t-4 border-[var(--court-accent)] bg-[#241a12] shadow-2xl sm:rounded-2xl sm:border-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex flex-none items-start justify-between gap-2 p-3">
          <div className="min-w-0">
            <h2 className="font-bold text-[var(--court-accent)]">
              証拠品ファイル({view.case.evidence.length})
            </h2>
            {present && (
              <p className="mt-0.5 text-xs">
                <span className="testimony-text">「{present.lineText}」</span>
                につきつける証拠品を選んでください
              </p>
            )}
          </div>
          <button onClick={onClose} className="shrink-0 rounded border px-3 py-1 text-sm">
            閉じる
          </button>
        </div>
        <ul className="min-h-0 flex-1 space-y-2 overflow-y-auto overscroll-contain px-3 pb-3">
          {view.case.evidence.map((e) => {
            const optionId = presentable.get(e.id);
            return (
              <li
                key={e.id}
                className={`rounded-lg border p-3 ${
                  optionId ? "border-red-400/70 bg-red-950/30" : "border-[var(--court-wood-light)] bg-black/20"
                } ${present && !optionId ? "opacity-50" : ""}`}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="font-bold">{e.name}</p>
                    <p className="text-sm opacity-80">{e.description}</p>
                  </div>
                  {present && optionId && (
                    <button
                      onClick={() => {
                        onClose();
                        present.onPresent(optionId);
                      }}
                      className="shrink-0 rounded-lg border-2 border-red-400/80 bg-red-800/70 px-3 py-2 text-sm font-bold"
                    >
                      つきつける
                    </button>
                  )}
                </div>
                <ul className="mt-1 list-disc pl-5 text-sm">
                  {e.details.map((d, i) => (
                    <li key={i}>{d}</li>
                  ))}
                </ul>
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}
