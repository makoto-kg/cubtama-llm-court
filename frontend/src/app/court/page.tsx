import { Suspense } from "react";

import { CourtScreen } from "@/components/CourtScreen";

// セッション ID はクエリ(?session=...)で受け取る。静的エクスポートのため動的パスは使わない。
export default function CourtPage() {
  return (
    <Suspense fallback={<p>読み込み中…</p>}>
      <CourtScreen />
    </Suspense>
  );
}
