"use client";

import { foundEvidence } from "@/lib/events";

/** 捜査画面。進捗と、見つかった証拠品候補が増えていく。 */
export function Investigation({
  progress,
  running,
  onStart,
}: {
  progress: string[];
  running: boolean;
  onStart: () => void;
}) {
  const found = foundEvidence(progress);
  const latest = [...progress].reverse().find((m) => !m.startsWith("証拠品候補: "));
  return (
    <section className="space-y-4 rounded-lg border border-[var(--court-wood-light)] bg-[var(--court-wood)]/60 p-5">
      <h2 className="text-xl font-bold">捜査</h2>
      {running ? (
        <p className="animate-pulse">{latest ?? "捜査を始めています…"}</p>
      ) : (
        <div className="space-y-2">
          <p>証拠品がまだありません。Web で捜査を始めます(SearXNG が必要)。</p>
          <button onClick={onStart} className="rounded bg-[var(--court-accent)] px-4 py-1 font-bold text-black">
            捜査を始める
          </button>
        </div>
      )}
      <div>
        <p className="font-bold">見つかった証拠品候補({found.length})</p>
        <ul className="mt-2 space-y-1">
          {found.map((title, i) => (
            <li key={i} className="rounded bg-black/30 px-3 py-1 text-sm">
              📁 {title}
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
