import type { TrialView } from "@/api/client";

import { currentTestimony, personName } from "./trial";

/** 開廷の場面で話す人。原告側はプレイヤー(証言の矛盾を追及する側)。 */
export type OpeningSpeaker = "judge" | "plaintiff" | "defendant";

export type OpeningLine = {
  speaker: OpeningSpeaker;
  text: string;
  /** この台詞の前に出すカットイン。 */
  cutIn?: string;
  /** 台詞と同時に木槌を鳴らす。 */
  gavel?: boolean;
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

/** 被告(役割が「被告」で始まる人物)。事件のデータに当事者の欄はないので、役割の書き方で決める。 */
export function defendantOf(view: TrialView) {
  return view.case.people.find((p) => p.role.startsWith("被告")) ?? null;
}

/**
 * 開廷の台本(裁判長の挨拶と超概要 → 原告・被告の宣言 → 審理開始)。
 * 事件の公開データだけから組み立てる(LLM は使わない。オフラインでも同じ台本になる)。
 */
export function openingScript(view: TrialView): OpeningLine[] {
  const first = currentTestimony(view) ?? view.case.testimonies[0];
  const witness = first ? personName(view, first.witness_id) : null;
  const defendant = defendantOf(view);
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
    { speaker: "judge", text: "原告側、準備はよろしいですか。" },
    {
      speaker: "plaintiff",
      text: "原告側、準備完了しています。証言に潜む矛盾を証拠品で明らかにし、真相を示してみせます。",
    },
    { speaker: "judge", text: "被告側はいかがですか。" },
    {
      speaker: "defendant",
      text: "被告側、準備完了しております。証人の証言に偽りはありません。それを証明いたしましょう。",
    },
    {
      speaker: "judge",
      gavel: true,
      text: witness
        ? `よろしい。それでは審理を始めます。最初の証人、${witness}さん。証言台へ。`
        : "よろしい。それでは審理を始めます。",
    },
  ];
}

/** 開廷の場面を見せるか。まだ尋問が始まっていない裁判だけ(再開した裁判では出さない)。 */
export function shouldShowOpening(view: TrialView): boolean {
  if (view.status === "finished" || view.status === "aborted") return false;
  return view.exchanges.length === 0 && view.stage !== "answering";
}
