"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { useOfflineIndex } from "@/hooks/useOffline";
import { clearSave, hasProgress, loadSave } from "@/lib/offline/save";

import { ConfirmDialog } from "./ConfirmDialog";

function trialUrl(caseId: string): string {
  return `/offline/trial/?case=${encodeURIComponent(caseId)}`;
}

/** オフラインで遊べる事件の一覧(同梱のパック。API は使わない)。 */
export function OfflineCaseList() {
  const router = useRouter();
  const { data, error } = useOfflineIndex();
  // 進行のある事件を「最初から」にするときの確認(ブラウザの confirm は使わない)
  const [confirmCase, setConfirmCase] = useState<{ id: string; title: string } | null>(null);

  /** 保存データを消して、最初から開廷する。 */
  function startOver(caseId: string) {
    try {
      clearSave(caseId);
    } catch {
      // ストレージが使えない環境では、もともと保存データがない
    }
    router.push(trialUrl(caseId));
  }

  return (
    <section className="space-y-3 rounded-lg border border-[var(--court-wood-light)] bg-[var(--court-wood)]/60 p-5">
      <ConfirmDialog
        open={confirmCase !== null}
        title="最初から始めますか?"
        message={`「${confirmCase?.title ?? ""}」の進行は消えます。開廷からやり直します。`}
        confirmLabel="最初から"
        onConfirm={() => {
          if (confirmCase) startOver(confirmCase.id);
          setConfirmCase(null);
        }}
        onCancel={() => setConfirmCase(null)}
      />
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
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
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
                <div className="flex gap-2 sm:shrink-0">
                  {resumable && (
                    <button
                      onClick={() => router.push(trialUrl(c.id))}
                      className="flex-1 rounded bg-[var(--court-accent)] px-4 py-2 font-bold text-black sm:flex-none"
                    >
                      続きから
                    </button>
                  )}
                  <button
                    onClick={() => (resumable ? setConfirmCase({ id: c.id, title: c.title }) : startOver(c.id))}
                    className={
                      resumable
                        ? "flex-1 rounded border border-[var(--court-accent)] px-4 py-2 font-bold text-[var(--court-accent)] sm:flex-none"
                        : "flex-1 rounded bg-[var(--court-accent)] px-4 py-2 font-bold text-black sm:flex-none"
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
