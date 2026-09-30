import Image from "next/image";
import type { ReactNode } from "react";

import { ASSETS } from "@/assets/manifest";

/**
 * 法廷の「カメラ」。話す人ごとに画面を切り替える(ADV の定番の見せ方。素材・意匠はオリジナル)。
 * 法廷に立つのは裁判官・検察官・被告の 3 人。被告は証言台(stand)で証言する(ADR 0017)。
 */
export type CourtShotKind = "judge" | "prosecutor" | "stand";

const FIGURE: Record<CourtShotKind, { src: string; width: number; height: number; align: string }> = {
  judge: { src: ASSETS.judge, width: 190, height: 228, align: "justify-center" },
  prosecutor: { src: ASSETS.prosecutor, width: 210, height: 273, align: "justify-start pl-[12%]" },
  stand: { src: ASSETS.witness, width: 200, height: 260, align: "justify-center" },
};

/** 背景の壁。席ごとに色味を変える。 */
const WALL: Record<CourtShotKind, string> = {
  judge: "court-wall-judge",
  prosecutor: "court-wall-prosecutor",
  stand: "court-wall-stand",
};

/** 手前の机(裁判官席・検察官席・証言台)。 */
function Desk({ kind }: { kind: CourtShotKind }) {
  if (kind === "judge") {
    return <div className="court-desk absolute inset-x-[8%] bottom-0 h-[44%] rounded-t-md" />;
  }
  if (kind === "stand") {
    return <div className="court-desk absolute inset-x-[34%] bottom-0 h-[40%] rounded-t-md" />;
  }
  return <div className="court-desk absolute bottom-0 left-0 right-[38%] h-[40%]" />;
}

/** 1 人を映す法廷の画面。`children` は画面の上に重ねるもの(台詞の枠など)。 */
export function CourtShot({
  kind,
  alt,
  speaking = false,
  shake = false,
  children,
}: {
  kind: CourtShotKind;
  alt: string;
  speaking?: boolean;
  shake?: boolean;
  children?: ReactNode;
}) {
  const figure = FIGURE[kind];
  return (
    <div className={`relative h-[46svh] max-h-[30rem] min-h-64 w-full sm:aspect-[16/10] sm:h-auto sm:max-h-[32rem] overflow-hidden rounded-lg ${shake ? "gavel-shake" : ""}`}>
      <div key={kind} className={`shot-in absolute inset-0 ${WALL[kind]}`}>
        <div className={`absolute inset-x-0 bottom-[30%] flex ${figure.align}`}>
          <Image
            src={figure.src}
            alt={alt}
            width={figure.width}
            height={figure.height}
            className={`h-auto w-[50%] max-w-64 sm:w-[30%] ${
              speaking ? "speaking" : ""
            }`}
            priority
          />
        </div>
        <Desk kind={kind} />
      </div>
      {children}
    </div>
  );
}

/** 画面の下に重ねる台詞の枠。左上に名札、右下に「次へ」の印。 */
export function DialogueBox({
  name,
  children,
  waiting = false,
  onClick,
}: {
  name: string;
  children: ReactNode;
  /** 読み終わって次の台詞を待っている(次へ の印を出す)。 */
  waiting?: boolean;
  onClick?: () => void;
}) {
  return (
    <div
      className={`absolute inset-x-1.5 bottom-1.5 sm:inset-x-4 sm:bottom-4 ${onClick ? "cursor-pointer" : ""}`}
      onClick={onClick}
    >
      <span className="dialogue-name relative z-10 ml-3 inline-block rounded-t-md px-4 py-0.5 text-sm font-bold">
        {name}
      </span>
      <div className="dialogue-box relative min-h-20 rounded-md px-3 py-2 text-[15px] leading-relaxed sm:min-h-28 sm:p-4 sm:text-lg">
        {children}
        {waiting && <span className="dialogue-next absolute bottom-2 right-3 text-sm">▼</span>}
      </div>
    </div>
  );
}
