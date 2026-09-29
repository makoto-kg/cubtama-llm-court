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
  const scripted = state.pack.meta.source === "scripted";
  const toolbar = (
    <>
      {finished && view.objections.length > 0 && (
        <button onClick={() => downloadObjections(caseId, view.objections)} className="rounded border px-2 py-0.5">
          異議を書き出す
        </button>
      )}
      <button
        onClick={() => {
          if (finished || window.confirm("最初からやり直しますか?(進行は消えます)")) restart();
        }}
        className="rounded border px-2 py-0.5"
      >
        やり直す
      </button>
      <Link href="/offline/" className="rounded border px-2 py-0.5">
        一覧へ
      </Link>
    </>
  );
  return (
    <div className="space-y-3">
      <p className="hidden text-xs lg:block">
        <span className="rounded bg-emerald-900/50 px-2 py-1">
          {scripted ? "オフライン(台本の応答)" : "オフライン(事前シミュレーションの応答)"}
        </span>
      </p>
      <TrialBoard
        key={state.seed}
        toolbar={toolbar}
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
        logNotice={
          scripted
            ? "この事件の応答は人が書いた台本です(LLM は使っていません)。"
            : "書記官の記録(思考ログ)は、台本と真相を含むため閉廷後に公開します。この画面の応答は事前に生成したものです。"
        }
      />
    </div>
  );
}
