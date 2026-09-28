import Image from "next/image";
import type { ReactNode } from "react";

import { ASSETS } from "@/assets/manifest";

/** 法廷の「カメラ」。話す人ごとに画面を切り替える(ADV の定番の見せ方。素材・意匠はオリジナル)。 */
export type CourtShotKind = "judge" | "plaintiff" | "defendant" | "witness";

const FIGURE: Record<CourtShotKind, { src: string; width: number; height: number; align: string }> = {
  judge: { src: ASSETS.judge, width: 190, height: 228, align: "justify-center" },
  plaintiff: { src: ASSETS.plaintiff, width: 210, height: 273, align: "justify-start pl-[12%]" },
  defendant: { src: ASSETS.defendant, width: 210, height: 273, align: "justify-end pr-[12%]" },
  witness: { src: ASSETS.witness, width: 200, height: 260, align: "justify-center" },
};

/** 背景の壁。席ごとに色味を変える。 */
const WALL: Record<CourtShotKind, string> = {
  judge: "court-wall-judge",
  plaintiff: "court-wall-plaintiff",
  defendant: "court-wall-defendant",
  witness: "court-wall-witness",
};

/** 手前の机(裁判長席・原告席・被告席・証言台)。 */
function Desk({ kind }: { kind: CourtShotKind }) {
  if (kind === "judge") {
    return <div className="court-desk absolute inset-x-[8%] bottom-0 h-[44%] rounded-t-md" />;
  }
  if (kind === "witness") {
    return <div className="court-desk absolute inset-x-[34%] bottom-0 h-[40%] rounded-t-md" />;
  }
  const side = kind === "plaintiff" ? "left-0 right-[38%]" : "left-[38%] right-0";
  return <div className={`court-desk absolute bottom-0 h-[40%] ${side}`} />;
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
    <div className={`relative aspect-[4/5] max-h-[32rem] sm:aspect-[16/10] w-full overflow-hidden rounded-lg ${shake ? "gavel-shake" : ""}`}>
      <div key={kind} className={`shot-in absolute inset-0 ${WALL[kind]}`}>
        <div className={`absolute inset-x-0 bottom-[30%] flex ${figure.align}`}>
          <Image
            src={figure.src}
            alt={alt}
            width={figure.width}
            height={figure.height}
            className={`h-auto w-[45%] max-w-64 sm:w-[30%] ${kind === "defendant" ? "-scale-x-100" : ""} ${
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
      className={`absolute inset-x-2 bottom-2 sm:inset-x-4 sm:bottom-4 ${onClick ? "cursor-pointer" : ""}`}
      onClick={onClick}
    >
      <span className="dialogue-name relative z-10 ml-3 inline-block rounded-t-md px-4 py-0.5 text-sm font-bold">
        {name}
      </span>
      <div className="dialogue-box relative min-h-24 rounded-md p-3 text-base leading-relaxed sm:min-h-28 sm:p-4 sm:text-lg">
        {children}
        {waiting && <span className="dialogue-next absolute bottom-2 right-3 text-sm">▼</span>}
      </div>
    </div>
  );
}
