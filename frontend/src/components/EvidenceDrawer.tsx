"use client";

import type { Evidence } from "@/api/client";

/** 証拠品ファイル(引き出し)。検証済みの事実と、本文からの引用を表示する。 */
export function EvidenceDrawer({
  evidence,
  open,
  onClose,
}: {
  evidence: Evidence[];
  open: boolean;
  onClose: () => void;
}) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/50" onClick={onClose}>
      <aside
        className="h-full w-full max-w-lg overflow-y-auto bg-[#241a12] p-4 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-bold">証拠品ファイル({evidence.length})</h2>
          <button onClick={onClose} className="rounded border px-2 text-sm">
            閉じる
          </button>
        </div>
        <ul className="space-y-4">
          {evidence.map((ev) => (
            <li key={ev.id} className="rounded border border-[var(--court-wood-light)] p-3">
              <p className="font-bold">
                <span className="mr-2 text-[var(--court-accent)]">{ev.id}</span>
                {ev.title}
              </p>
              <p className="text-xs opacity-70">
                {ev.published_date ?? "日付不明"} /{" "}
                <a href={ev.source_url} target="_blank" rel="noreferrer" className="underline">
                  出典
                </a>
              </p>
              <p className="mt-1 text-sm">{ev.summary}</p>
              <ul className="mt-2 space-y-1 text-sm">
                {ev.key_facts.map((fact, i) => (
                  <li key={i} className={fact.quote_verified ? "" : "opacity-50"}>
                    {fact.quote_verified ? "✓" : "✗ 未検証"} {fact.text}
                    <span className="block pl-4 text-xs opacity-70">「{fact.quote}」</span>
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
      </aside>
    </div>
  );
}
