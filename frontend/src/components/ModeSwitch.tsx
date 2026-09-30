"use client";

import type { ReactNode } from "react";

import { useAppMode } from "@/hooks/useAppMode";
import { type AppMode, MODE_LABELS } from "@/lib/mode";

const DESCRIPTIONS: Record<AppMode, string> = {
  offline: "同梱の事件で裁判を遊ぶ。バックエンド・LLM サーバーは不要",
  online: "バックエンドにつないで、ディベートや生成した事件で遊ぶ(llm-court serve が必要)",
};

/** 遊び方のモード(オフライン / オンライン)の切り替え。既定はオフライン。 */
export function ModeSwitch() {
  const [mode, setMode] = useAppMode();
  return (
    <div className="space-y-1.5">
      <div role="radiogroup" aria-label="遊び方" className="mx-auto flex w-full max-w-sm rounded-full bg-black/40 p-1">
        {(Object.keys(MODE_LABELS) as AppMode[]).map((m) => (
          <button
            key={m}
            role="radio"
            aria-checked={mode === m}
            onClick={() => setMode(m)}
            className={`flex-1 rounded-full py-2 text-sm font-bold ${
              mode === m ? "bg-[var(--court-accent)] text-black" : "opacity-70"
            }`}
          >
            {MODE_LABELS[m]}
          </button>
        ))}
      </div>
      <p className="text-center text-xs opacity-70">{DESCRIPTIONS[mode]}</p>
    </div>
  );
}

/** 選んだモードの画面(タイトルの中身)。 */
export function ByMode({ offline, online }: { offline: ReactNode; online: ReactNode }) {
  const [mode] = useAppMode();
  return <>{mode === "online" ? online : offline}</>;
}
