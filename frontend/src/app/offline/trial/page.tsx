import { Suspense } from "react";

import { OfflineTrialScreen } from "@/components/OfflineTrialScreen";

// 事件の ID はクエリ(?case=...)で受け取る。静的エクスポートのため動的パスは使わない。
export default function OfflineTrialPage() {
  return (
    <Suspense fallback={<p>読み込み中…</p>}>
      <OfflineTrialScreen />
    </Suspense>
  );
}
