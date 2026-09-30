import type { TrialView } from "@/api/client";

import { defendantOf, type OpeningLine } from "./opening";

/** 判決の場面のカットイン(オリジナルの文言)。 */
export const VERDICT_CUT_IN = { verdict: "判決", guilty: "有罪", close: "閉廷" } as const;

/** 事件に判決の刑罰・被告の反応がないとき(生成した事件など)の定型文。 */
export const DEFAULT_VERDICT = {
  sentence: null,
  defendant_reaction: "……はい。すべて、わたしがやりました。深く反省しています……。",
} as const;

/**
 * 判決の場面(ADR 0020): 全矛盾を解いたあと、裁判官が有罪と刑罰を言い渡し、被告が反応する。
 * 刑罰と反応は事件のデータ(解説の `verdict`)から。なければ定型文。LLM は使わない。
 */
export function verdictScript(view: TrialView): OpeningLine[] {
  const verdict = view.explanation?.verdict ?? null;
  const name = defendantOf(view)?.name ?? null;
  const sentence = verdict?.sentence ?? DEFAULT_VERDICT.sentence;
  return [
    {
      speaker: "judge",
      cutIn: VERDICT_CUT_IN.verdict,
      gavel: true,
      text: "それでは、判決を言い渡します。",
    },
    {
      speaker: "judge",
      cutIn: VERDICT_CUT_IN.guilty,
      text: name ? `被告、${name}。あなたを「有罪」とします。` : "被告を「有罪」とします。",
    },
    {
      speaker: "judge",
      gavel: true,
      text: sentence
        ? `刑罰は……「${sentence}」とします!`
        : "被告には、自らのおこないを深く反省してもらいます。",
    },
    { speaker: "defendant", text: verdict?.defendant_reaction ?? DEFAULT_VERDICT.defendant_reaction },
  ];
}

/** 判決の場面を見せるか。全矛盾を解いて閉廷した裁判だけ(ゲージが尽きた・中断した裁判は出さない)。 */
export function hasVerdictScene(view: TrialView): boolean {
  return view.status === "finished" && view.result === "solved";
}
