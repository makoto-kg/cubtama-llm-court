import Image from "next/image";
import type { ReactNode } from "react";

import { TITLE_LOGO } from "@/assets/manifest";

/** 空いた場所にうっすら出すタイトルロゴ(白黒)。飾りだけで、操作の邪魔をしない。 */
function Watermark({ className }: { className: string }) {
  return (
    <Image
      src={TITLE_LOGO.src}
      alt=""
      aria-hidden
      width={TITLE_LOGO.width}
      height={TITLE_LOGO.height}
      className={`shell-watermark pointer-events-none h-auto select-none ${className}`}
    />
  );
}

/**
 * 法廷のプレイ画面の枠。スマホ(縦画面)では画面いっぱいに固定し、
 * 上から「状態のバー」「法廷の画面(キャラクターと台詞)」「操作」の順に並べる。
 * キャラクターと台詞は画面に固定し、スクロールするのは操作の欄だけにする。
 * 広い画面(lg 以上)では通常の流れに戻し、`side` を右の列に出す。
 * 操作の欄(スマホ)と右の列(広い画面)の空いた場所には、白黒のタイトルロゴをうっすら出す。
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
          <div className="max-lg:relative max-lg:min-h-0 max-lg:flex-1">
            <Watermark className="absolute bottom-[8%] left-1/2 w-[78%] max-w-sm -translate-x-1/2 lg:hidden" />
            {panel && (
              <div className="max-lg:relative max-lg:h-full max-lg:overflow-y-auto max-lg:overscroll-contain max-lg:px-2 max-lg:py-2">
                {panel}
              </div>
            )}
          </div>
        </div>
        <div className="hidden space-y-4 lg:block">
          {side}
          <Watermark className="mx-auto w-[85%] max-w-md pt-4" />
        </div>
      </div>
    </div>
  );
}
