"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { openTrial, useCases } from "@/hooks/useApi";

/** 裁判(事件を解く): 生成済みの事件を選んで開廷する。 */
export function CasePicker() {
  const router = useRouter();
  const [all, setAll] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { data: cases, error: loadError } = useCases(all);

  async function start(caseId: string) {
    setBusy(caseId);
    setError(null);
    try {
      router.push(`/trial/?session=${await openTrial(caseId)}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(null);
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="font-bold">事件を選ぶ</p>
        <label className="flex items-center gap-1 text-xs opacity-80">
          <input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} />
          未検証・解けない事件も表示
        </label>
      </div>
      {loadError && <p className="text-sm text-red-300">API に接続できません({loadError})</p>}
      {error && <p className="text-sm text-red-300">{error}</p>}
      {cases && cases.length === 0 && (
        <p className="text-sm opacity-70">
          遊べる事件がありません。<code>llm-court case generate</code> で生成してください。
        </p>
      )}
      <ul className="space-y-2">
        {cases?.map((c) => (
          <li key={c.id} className="rounded border border-[var(--court-wood-light)] p-3">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="font-bold">{c.title}</p>
                <p className="text-xs opacity-70">
                  テーマ: {c.theme} / 証言 {c.testimonies} / 矛盾 {c.contradictions}
                  {c.solve_rate != null && ` / solver の解答率 ${Math.round(c.solve_rate * 100)}%`}
                  {!c.solvable && " / 未合格"}
                </p>
                <p className="mt-1 text-sm">{c.overview}</p>
              </div>
              <button
                onClick={() => void start(c.id)}
                disabled={busy !== null}
                className="shrink-0 rounded bg-[var(--court-accent)] px-4 py-1 font-bold text-black disabled:opacity-50"
              >
                {busy === c.id ? "開廷中…" : "開廷"}
              </button>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
