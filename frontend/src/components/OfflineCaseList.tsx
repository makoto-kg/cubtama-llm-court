"use client";

import { useRouter } from "next/navigation";

import { useOfflineIndex } from "@/hooks/useOffline";
import { clearSave, hasProgress, loadSave } from "@/lib/offline/save";

function trialUrl(caseId: string): string {
  return `/offline/trial/?case=${encodeURIComponent(caseId)}`;
}

/** オフラインで遊べる事件の一覧(同梱のパック。API は使わない)。 */
export function OfflineCaseList() {
  const router = useRouter();
  const { data, error } = useOfflineIndex();

  /** 保存データを消して、最初から開廷する。進行があれば確認する。 */
  function startOver(caseId: string, resumable: boolean) {
    if (resumable && !window.confirm("最初からやり直しますか?(この事件の進行は消えます)")) return;
    try {
      clearSave(caseId);
    } catch {
      // ストレージが使えない環境では、もともと保存データがない
    }
    router.push(trialUrl(caseId));
  }

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
          let resumable = false;
          try {
            resumable = hasProgress(loadSave(c.id));
          } catch {
            // ストレージが使えない環境では、続きはない
          }
          return (
            <li key={c.id} className="rounded border border-[var(--court-wood-light)] p-3">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
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
                <div className="flex shrink-0 gap-2">
                  {resumable && (
                    <button
                      onClick={() => router.push(trialUrl(c.id))}
                      className="rounded bg-[var(--court-accent)] px-4 py-1.5 font-bold text-black"
                    >
                      続きから
                    </button>
                  )}
                  <button
                    onClick={() => startOver(c.id, resumable)}
                    className={
                      resumable
                        ? "rounded border border-[var(--court-accent)] px-4 py-1.5 font-bold text-[var(--court-accent)]"
                        : "rounded bg-[var(--court-accent)] px-4 py-1.5 font-bold text-black"
                    }
                  >
                    最初から
                  </button>
                </div>
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
