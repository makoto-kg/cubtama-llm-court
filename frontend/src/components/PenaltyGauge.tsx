"use client";

import { useState } from "react";

export function PenaltyGauge({ remaining, max }: { remaining: number; max: number }) {
  // 減った瞬間、減った目盛りを光らせる(n はアニメーションをやり直すためのキー)
  const [prev, setPrev] = useState(remaining);
  const [hit, setHit] = useState<{ from: number; to: number; n: number } | null>(null);
  if (remaining !== prev) {
    setPrev(remaining);
    setHit(remaining < prev ? { from: remaining, to: prev, n: (hit?.n ?? 0) + 1 } : null);
  }
  return (
    <div className="flex items-center gap-1.5 text-xs lg:gap-2 lg:text-sm" aria-label={`ペナルティゲージ ${remaining}/${max}`}>
      <span className="max-sm:sr-only">ゲージ</span>
      <div className="flex gap-1">
        {Array.from({ length: max }, (_, i) => {
          const lost = hit !== null && i >= hit.from && i < hit.to;
          return (
            <span
              key={lost ? `${i}-${hit.n}` : i}
              className={`h-3 w-4 rounded-sm lg:h-4 lg:w-6 border border-[var(--court-accent)] ${
                i < remaining ? "bg-[var(--court-accent)]" : "bg-transparent"
              } ${lost ? "gauge-hit" : ""}`}
            />
          );
        })}
      </div>
      <span className="tabular-nums">
        {Math.max(remaining, 0)}/{max}
      </span>
    </div>
  );
}
