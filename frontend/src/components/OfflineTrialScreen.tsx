"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";

import { useOfflineTrial } from "@/hooks/useOffline";
import { toTrialView } from "@/lib/offline/engine";
import { useOfflineStore } from "@/store/offline";

import { TrialBoard } from "./TrialScreen";

function downloadObjections(caseId: string, objections: unknown[]) {
  const blob = new Blob([JSON.stringify({ case_id: caseId, objections }, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `objections-${caseId}.json`;
  a.click();
  URL.revokeObjectURL(url);
}

/** オフラインの裁判画面(同梱のパックで進行する。API は使わない)。 */
export function OfflineTrialScreen() {
  const caseId = useSearchParams().get("case");
  useOfflineTrial(caseId);
  const { state, streaming, cutIn, error, choose, answer, object, restart, clearCutIn } = useOfflineStore();

  if (!caseId) {
    return (
      <p>
        事件が指定されていません。<Link href="/offline/">一覧へ</Link>
      </p>
    );
  }
  if (!state || state.pack.case.id !== caseId) return <p>{error ?? "読み込み中…"}</p>;

  const view = toTrialView(state);
  const finished = view.status === "finished";
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
        <span className="rounded bg-emerald-900/50 px-2 py-1">オフライン(事前シミュレーションの応答)</span>
        <div className="flex gap-2">
          {finished && view.objections.length > 0 && (
            <button onClick={() => downloadObjections(caseId, view.objections)} className="rounded border px-2 py-1">
              異議を書き出す(JSON)
            </button>
          )}
          <button
            onClick={() => {
              if (finished || window.confirm("最初からやり直しますか?(進行は消えます)")) restart();
            }}
            className="rounded border px-2 py-1"
          >
            最初からやり直す
          </button>
          <Link href="/offline/" className="rounded border px-2 py-1">
            一覧へ
          </Link>
        </div>
      </div>
      <TrialBoard
        key={state.seed}
        view={view}
        streaming={streaming}
        progress={null}
        running={streaming !== null}
        error={error}
        cutIn={cutIn}
        onClearCutIn={clearCutIn}
        calls={state.calls}
        onChoose={choose}
        onAnswer={answer}
        onObject={async (kind, id, comment) => object(kind, id, comment)}
        logNotice="書記官の記録(思考ログ)は、台本と真相を含むため閉廷後に公開します。この画面の応答は事前に生成したものです。"
      />
    </div>
  );
}
