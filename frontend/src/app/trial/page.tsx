import { Suspense } from "react";

import { TrialScreen } from "@/components/TrialScreen";

// 裁判のセッション ID はクエリ(?session=...)で受け取る。静的エクスポートのため動的パスは使わない。
export default function TrialPage() {
  return (
    <Suspense fallback={<p>読み込み中…</p>}>
      <TrialScreen />
    </Suspense>
  );
}
