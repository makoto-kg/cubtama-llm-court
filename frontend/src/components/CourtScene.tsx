import Image from "next/image";
import type { ReactNode } from "react";

import { type CharacterPose, trialSprite } from "@/assets/manifest";

/**
 * 法廷の「カメラ」。話す人ごとに画面を切り替える(ADV の定番の見せ方。素材・意匠はオリジナル)。
 * 法廷に立つのは裁判官・検察官・被告の 3 人。被告は証言台(stand)で証言する(ADR 0017)。
 */
export type CourtShotKind = "judge" | "prosecutor" | "stand";

const ROLE = { judge: "judge", prosecutor: "prosecutor", stand: "defendant" } as const;

type Placement = { height: string; box: string; position: string };

/** 立ち絵の置き場所(画面の高さに対する立ち絵の高さと、横の寄せ方)。 */
const PLACEMENT: Record<CourtShotKind, Placement> = {
  judge: { height: "h-[96%]", box: "inset-x-0 justify-center", position: "object-bottom" },
  prosecutor: { height: "h-[98%]", box: "inset-x-0 justify-center", position: "object-bottom" },
  stand: { height: "h-[97%]", box: "inset-x-0 justify-center", position: "object-bottom" },
};

/** つきつけるときは左に寄せ、右の相手を指さす。 */
const IGIARI_PLACEMENT: Placement = {
  height: "h-[98%]",
  box: "left-[4%] right-0 justify-start",
  position: "object-left-bottom",
};

/** 表情ごとの動き(困惑は震え、有罪はうなだれる、つきつけるは踏み込む)。 */
const POSE_CLASS: Record<CharacterPose, string> = {
  standard: "",
  nervous: "pose-nervous",
  lose: "pose-lose",
  igiari: "pose-igiari",
};

/** 背景の壁。席ごとに色味と飾りを変える。 */
function Backdrop({ kind, pose }: { kind: CourtShotKind; pose: CharacterPose }) {
  if (pose === "igiari") {
    return (
      <div className="court-wall-action absolute inset-0">
        <div className="court-speedlines absolute inset-0" />
      </div>
    );
  }
  return (
    <div className={`absolute inset-0 court-wall-${kind}`}>
      {kind === "judge" && <div className="court-emblem absolute left-1/2 top-[6%] -translate-x-1/2" />}
      {kind === "stand" && <div className="court-spotlight absolute inset-0" />}
      {pose === "lose" && <div className="court-gloom absolute inset-0" />}
    </div>
  );
}

/** 手前の机(裁判官席・検察官席・証言台)。 */
function Desk({ kind, pose }: { kind: CourtShotKind; pose: CharacterPose }) {
  if (kind === "judge") {
    return <div className="court-desk absolute inset-x-[4%] bottom-0 h-[24%] rounded-t-sm" />;
  }
  if (kind === "stand") {
    return <div className="court-desk court-desk-stand absolute inset-x-[26%] bottom-0 h-[26%] rounded-t-sm" />;
  }
  // つきつけるときは机を画面の端へ寄せ、手前に踏み込んだように見せる
  return pose === "igiari" ? (
    <div className="court-desk absolute bottom-0 left-0 right-[62%] h-[16%]" />
  ) : (
    <div className="court-desk absolute inset-x-[10%] bottom-0 h-[24%] rounded-t-sm" />
  );
}

/** 1 人を映す法廷の画面。`children` は画面の上に重ねるもの(台詞の枠など)。 */
export function CourtShot({
  kind,
  alt,
  pose = "standard",
  speaking = false,
  shake = false,
  children,
}: {
  kind: CourtShotKind;
  alt: string;
  /** 立ち絵の表情。その役にない表情は通常の立ち絵になる。 */
  pose?: CharacterPose;
  speaking?: boolean;
  shake?: boolean;
  children?: ReactNode;
}) {
  const sprite = trialSprite(ROLE[kind], pose);
  const place = pose === "igiari" ? IGIARI_PLACEMENT : PLACEMENT[kind];
  return (
    <div
      className={`court-frame relative h-[46svh] max-h-[30rem] min-h-64 w-full sm:aspect-[16/10] sm:h-auto sm:max-h-[32rem] overflow-hidden rounded-lg ${shake ? "gavel-shake" : ""}`}
    >
      <div key={`${kind}-${pose === "igiari" ? "action" : "still"}`} className="shot-in absolute inset-0">
        <Backdrop kind={kind} pose={pose} />
        <div className={`absolute bottom-0 top-0 flex items-end ${place.box} ${speaking ? "speaking" : ""}`}>
          <Image
            key={sprite.src}
            src={sprite.src}
            alt={alt}
            width={sprite.width}
            height={sprite.height}
            className={`court-figure ${place.height} w-auto max-w-full object-contain ${place.position} ${POSE_CLASS[pose]}`}
            priority
          />
        </div>
        <Desk kind={kind} pose={pose} />
        <div className="court-vignette pointer-events-none absolute inset-0" />
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
