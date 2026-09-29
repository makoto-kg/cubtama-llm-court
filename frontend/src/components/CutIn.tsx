"use client";

import { useEffect } from "react";

import { useCourtStore } from "@/store/court";

const DURATION_MS = 1200;

type CutInState = { text: string; key: number; strong?: boolean } | null;

/** カットインの表示(オリジナルの文言と演出)。`strong` は証言が崩れた瞬間などの強い演出。 */
export function CutInView({ cutIn, onDone }: { cutIn: CutInState; onDone: () => void }) {
  useEffect(() => {
    if (!cutIn) return;
    const timer = setTimeout(onDone, cutIn.strong ? DURATION_MS * 1.5 : DURATION_MS);
    return () => clearTimeout(timer);
  }, [cutIn, onDone]);

  if (!cutIn) return null;
  return (
    <div
      className={`pointer-events-none fixed inset-0 z-50 flex items-center justify-center ${
        cutIn.strong ? "cut-in-flash" : ""
      }`}
    >
      <div
        key={cutIn.key}
        className={`cut-in whitespace-nowrap border-y-4 border-[var(--court-accent)] bg-black/85 px-8 py-4 font-black tracking-widest text-[var(--court-accent)] sm:px-24 sm:py-6 ${
          cutIn.strong ? "cut-in-strong text-5xl sm:text-7xl" : "text-4xl sm:text-6xl"
        }`}
      >
        {cutIn.text}
      </div>
    </div>
  );
}

/** 指摘・反論の瞬間に出るカットイン(ディベート画面)。 */
export function CutIn() {
  const cutIn = useCourtStore((s) => s.cutIn);
  const clear = useCourtStore((s) => s.clearCutIn);
  return <CutInView cutIn={cutIn} onDone={clear} />;
}
