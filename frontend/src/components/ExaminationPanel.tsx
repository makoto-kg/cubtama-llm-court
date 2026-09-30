"use client";

import type { TrialOption, TrialView } from "@/api/client";
import { stepLine } from "@/lib/trial";

type Testimony = TrialView["case"]["testimonies"][number];

/**
 * 尋問の操作。証言の行を ◀ ▶ で切り替え、いま指している行に「ゆさぶる」か「つきつける」を選ぶ。
 * つきつけるは、証拠品ファイルを法廷の画面に重ねて開き、その行に並んだ証拠品から選ぶ(`onPresent`)。
 */
export function ExaminationPanel({
  testimony,
  lineId,
  options,
  solved,
  running,
  onLine,
  onChoose,
  onPresent,
  onReplay,
}: {
  testimony: Testimony;
  lineId: string | null;
  /** いま指している行の選択肢。 */
  options: TrialOption[];
  solved: Set<string>;
  running: boolean;
  onLine: (lineId: string) => void;
  onChoose: (optionId: string) => void;
  onPresent: () => void;
  onReplay: () => void;
}) {
  const probe = options.find((o) => o.kind === "probe");
  const presents = options.filter((o) => o.kind === "present");
  const isSolved = lineId !== null && solved.has(lineId);
  const step = (delta: number) => {
    const next = stepLine(
      testimony.lines.map((l) => l.id),
      lineId,
      delta,
    );
    if (next) onLine(next);
  };

  return (
    <section className="space-y-2">
      <div className="flex items-center justify-between gap-2 text-xs">
        <span className="truncate opacity-70">{testimony.title}</span>
        <button onClick={onReplay} disabled={running} className="shrink-0 rounded border px-2 py-0.5 disabled:opacity-40">
          証言をもう一度聞く
        </button>
      </div>

      <div className="flex items-center gap-2">
        <button
          onClick={() => step(-1)}
          aria-label="前の証言"
          className="h-11 w-11 shrink-0 rounded-full border-2 border-[var(--court-accent)] text-lg font-bold"
        >
          ◀
        </button>
        <div className="flex flex-1 justify-center gap-1.5">
          {testimony.lines.map((line, i) => (
            <button
              key={line.id}
              onClick={() => onLine(line.id)}
              aria-label={`${i + 1} 行目`}
              className={`h-9 min-w-9 rounded-full px-2 text-sm font-bold ${
                line.id === lineId
                  ? "bg-[var(--court-accent)] text-black"
                  : solved.has(line.id)
                    ? "bg-emerald-800/70 text-emerald-200"
                    : "bg-black/40"
              }`}
            >
              {solved.has(line.id) ? "✓" : i + 1}
            </button>
          ))}
        </div>
        <button
          onClick={() => step(1)}
          aria-label="次の証言"
          className="h-11 w-11 shrink-0 rounded-full border-2 border-[var(--court-accent)] text-lg font-bold"
        >
          ▶
        </button>
      </div>

      {running ? (
        <p className="animate-pulse py-3 text-center text-sm opacity-80">被告が答えています…</p>
      ) : isSolved ? (
        <p className="py-3 text-center text-sm text-emerald-300">この証言は崩れました。他の証言を調べましょう</p>
      ) : (
        <div className="grid grid-cols-2 gap-2">
          <button
            onClick={() => probe && onChoose(probe.id)}
            disabled={!probe}
            className="rounded-lg border-2 border-sky-400/80 bg-sky-950/60 py-3 font-bold disabled:opacity-30"
          >
            ゆさぶる
          </button>
          <button
            onClick={onPresent}
            disabled={presents.length === 0}
            className="rounded-lg border-2 border-red-400/80 bg-red-950/60 py-3 font-bold disabled:opacity-30"
          >
            つきつける
          </button>
        </div>
      )}
    </section>
  );
}
