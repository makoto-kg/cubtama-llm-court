"use client";

import { useEffect } from "react";

import { useCourtStore } from "@/store/court";

const DURATION_MS = 1200;

/** 指摘・反論の瞬間に出るカットイン(オリジナルの文言と演出)。 */
export function CutIn() {
  const cutIn = useCourtStore((s) => s.cutIn);
  const clear = useCourtStore((s) => s.clearCutIn);

  useEffect(() => {
    if (!cutIn) return;
    const timer = setTimeout(clear, DURATION_MS);
    return () => clearTimeout(timer);
  }, [cutIn, clear]);

  if (!cutIn) return null;
  return (
    <div className="pointer-events-none fixed inset-0 z-50 flex items-center justify-center">
      <div
        key={cutIn.key}
        className="cut-in border-y-4 border-[var(--court-accent)] bg-black/85 px-24 py-6 text-6xl font-black tracking-widest text-[var(--court-accent)]"
      >
        {cutIn.text}
      </div>
    </div>
  );
}
