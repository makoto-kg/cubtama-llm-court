import type { TrialView } from "@/api/client";
import type { CharacterPose } from "@/assets/manifest";

import { currentTestimony, personName } from "./trial";

/** 開廷の場面で話す人。法廷に立つのは裁判官・検察官(プレイヤー)・被告の 3 人(ADR 0017)。 */
export type OpeningSpeaker = "judge" | "prosecutor" | "defendant";

export type OpeningLine = {
  speaker: OpeningSpeaker;
  text: string;
  /** この台詞の前に出すカットイン。 */
  cutIn?: string;
  /** 台詞と同時に木槌を鳴らす。 */
  gavel?: boolean;
  /** 話す人の表情(省略時は通常)。 */
  pose?: CharacterPose;
};

/** 開廷の場面のカットイン(オリジナルの文言)。 */
export const OPENING_CUT_IN = { open: "開廷", start: "審理開始" } as const;

/** 概要の「超概要」: 最初の 1 文。長すぎれば切り詰める。 */
export function briefOverview(overview: string, maxLength = 80): string {
  const text = overview.trim();
  const end = text.indexOf("。");
  const first = end >= 0 ? text.slice(0, end + 1) : text;
  return first.length > maxLength ? `${first.slice(0, maxLength - 1)}…` : first;
}

/**
 * 被告。事件の `defendant_id` で決まる。被告を持たない旧形式の事件は、役割が「被告」で始まる人物。
 */
export function defendantOf(view: TrialView) {
  const people = view.case.people;
  return (
    people.find((p) => p.id === view.case.defendant_id) ?? people.find((p) => p.role.startsWith("被告")) ?? null
  );
}

/**
 * 開廷の台本(裁判官の挨拶と超概要・被告の紹介 → 検察官と被告の宣言 → 審理開始)。
 * 事件の公開データだけから組み立てる(LLM は使わない。オフラインでも同じ台本になる)。
 */
export function openingScript(view: TrialView): OpeningLine[] {
  const defendant = defendantOf(view);
  // 旧形式の事件(被告なし)は、最初に証言する人を証言台に呼ぶ
  const first = currentTestimony(view) ?? view.case.testimonies[0];
  const standName = defendant?.name ?? (first ? personName(view, first.witness_id) : null);
  return [
    {
      speaker: "judge",
      cutIn: OPENING_CUT_IN.open,
      gavel: true,
      text: `ただいまより、「${view.case.title}」の審理を開廷します。`,
    },
    { speaker: "judge", text: `本件の概要です。${briefOverview(view.case.overview)}` },
    ...(defendant
      ? [{ speaker: "judge" as const, text: `被告は、${defendant.name}。${defendant.description}` }]
      : []),
    { speaker: "judge", text: "検察側、準備はよろしいですか。" },
    {
      speaker: "prosecutor",
      text:
        view.case.prosecutor_speech === "cat"
          ? "検察側、準備はできてるにゃ。被告の証言のウソ、証拠品でぜんぶ暴いてみせるにゃ!"
          : "検察側、準備完了しています。被告の証言に潜む矛盾を、証拠品で明らかにしてみせます。",
    },
    { speaker: "judge", text: standName ? `被告、${standName}さん。証言台へ。` : "被告は証言台へ。" },
    { speaker: "defendant", text: "……はい。わたしは何も偽っていません。すべてお話ししますにゃ。" },
    {
      speaker: "judge",
      gavel: true,
      text: "よろしい。それでは、検察官による被告人尋問を始めます。",
    },
  ];
}

/** 開廷の場面を見せるか。まだ尋問が始まっていない裁判だけ(再開した裁判では出さない)。 */
export function shouldShowOpening(view: TrialView): boolean {
  if (view.status === "finished" || view.status === "aborted") return false;
  return view.exchanges.length === 0 && view.stage !== "answering";
}
