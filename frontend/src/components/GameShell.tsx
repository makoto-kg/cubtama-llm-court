import type { ReactNode } from "react";

/**
 * 法廷のプレイ画面の枠。スマホ(縦画面)では画面いっぱいに固定し、
 * 上から「状態のバー」「法廷の画面(キャラクターと台詞)」「操作」の順に並べる。
 * キャラクターと台詞は画面に固定し、スクロールするのは操作の欄だけにする。
 * 広い画面(lg 以上)では通常の流れに戻し、`side` を右の列に出す。
 */
export function GameShell({
  top,
  stage,
  panel,
  side,
}: {
  top: ReactNode;
  stage: ReactNode;
  panel?: ReactNode;
  side?: ReactNode;
}) {
  return (
    <div className="max-lg:fixed max-lg:inset-0 max-lg:z-30 max-lg:flex max-lg:flex-col max-lg:bg-[#1a1410] max-lg:pb-[env(safe-area-inset-bottom)] lg:space-y-3">
      <div className="flex-none max-lg:px-2 max-lg:pt-2">{top}</div>
      <div className="lg:grid lg:grid-cols-[3fr_2fr] lg:gap-4 max-lg:flex max-lg:min-h-0 max-lg:flex-1 max-lg:flex-col">
        <div className="max-lg:flex max-lg:min-h-0 max-lg:flex-1 max-lg:flex-col lg:space-y-3">
          <div className="flex-none max-lg:px-2 max-lg:pt-2">{stage}</div>
          {panel && (
            <div className="max-lg:min-h-0 max-lg:flex-1 max-lg:overflow-y-auto max-lg:overscroll-contain max-lg:px-2 max-lg:py-2">
              {panel}
            </div>
          )}
        </div>
        {side && <div className="hidden space-y-4 lg:block">{side}</div>}
      </div>
    </div>
  );
}
