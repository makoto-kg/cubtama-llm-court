"use client";

import Link from "next/link";

import { useOfflineIndex } from "@/hooks/useOffline";
import { loadSave } from "@/lib/offline/save";

/** オフラインで遊べる事件の一覧(同梱のパック。API は使わない)。 */
export function OfflineCaseList() {
  const { data, error } = useOfflineIndex();
  return (
    <section className="space-y-3 rounded-lg border border-[var(--court-wood-light)] bg-[var(--court-wood)]/60 p-5">
      <div>
        <h2 className="text-lg font-bold">裁判(オフライン)</h2>
        <p className="text-xs opacity-70">
          事前に用意した被告の応答(LLM で事前にシミュレーションしたもの、またはチュートリアルの台本)で遊びます。バックエンドや LLM サーバーは不要です。
        </p>
      </div>
      {error && <p className="text-sm text-red-300">事件の一覧を読み込めません({error})</p>}
      {data && data.cases.length === 0 && <p className="text-sm opacity-70">同梱の事件がありません</p>}
      <ul className="space-y-2">
        {data?.cases.map((c) => {
          const saved = loadSave(c.id);
          const resumable = Boolean(saved && saved.actions.length > 0);
          return (
            <li key={c.id} className="rounded border border-[var(--court-wood-light)] p-3">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="font-bold">
                    {c.tutorial && (
                      <span className="mr-2 rounded bg-emerald-700 px-2 py-0.5 text-xs">チュートリアル</span>
                    )}
                    {c.title}
                  </p>
                  <p className="text-xs opacity-70">
                    テーマ: {c.theme} / 証言 {c.testimonies} / 矛盾 {c.contradictions}
                  </p>
                  <p className="mt-1 text-sm">{c.overview}</p>
                </div>
                <Link
                  href={`/offline/trial/?case=${c.id}`}
                  className="shrink-0 rounded bg-[var(--court-accent)] px-4 py-1 font-bold text-black"
                >
                  {resumable ? "続きから" : "開廷"}
                </Link>
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
