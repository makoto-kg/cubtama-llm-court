import Image from "next/image";

import type { Side } from "@/api/client";
import { ASSETS, SPEAKER_NAMES } from "@/assets/manifest";

type Speaker = Side | "judge" | null;

function Figure({
  who,
  speaking,
  human,
}: {
  who: "affirmative" | "negative" | "judge";
  speaking: boolean;
  human: boolean;
}) {
  return (
    <div className={`flex flex-col items-center transition-opacity ${speaking ? "opacity-100" : "opacity-60"}`}>
      <Image
        src={ASSETS[who]}
        alt={SPEAKER_NAMES[who]}
        width={who === "judge" ? 120 : 150}
        height={who === "judge" ? 166 : 195}
        className={speaking ? "speaking" : ""}
        priority
      />
      <span className="mt-1 rounded bg-black/40 px-2 text-xs">
        {SPEAKER_NAMES[who]}
        {human && "(あなた)"}
      </span>
    </div>
  );
}

/** 法廷の立ち絵(左に肯定側、中央奥に裁判長、右に否定側)。 */
export function Stage({ speaker, humanSide }: { speaker: Speaker; humanSide: Side | null }) {
  return (
    <div className="relative flex h-64 items-end justify-between overflow-hidden rounded-t-lg bg-gradient-to-b from-[#2a1d14] to-[var(--court-wood)] px-8 pb-2">
      <Figure who="affirmative" speaking={speaker === "affirmative"} human={humanSide === "affirmative"} />
      <div className="mb-16">
        <Figure who="judge" speaking={speaker === "judge"} human={false} />
      </div>
      <Figure who="negative" speaking={speaker === "negative"} human={humanSide === "negative"} />
    </div>
  );
}
