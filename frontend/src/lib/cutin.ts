import type { ChoiceOption, Side } from "@/api/client";
import type { TurnKey } from "./stream";

/** カットインの文言(オリジナル。既存作品の決め台詞は使わない)。 */
export const CUT_IN_TEXT = {
  contradiction: "反証!",
  probe: "確認!",
  rebuttal: "反論!",
} as const;

export function cutInForChoice(option: ChoiceOption): string | null {
  if (option.kind === "contradiction") return CUT_IN_TEXT.contradiction;
  if (option.kind === "probe") return CUT_IN_TEXT.probe;
  return null;
}

/** LLM 側の反論の開始時に出す。人間側の発言は選択時に出すのでここでは出さない。 */
export function cutInForTurn(turn: TurnKey, humanSide: Side | null | undefined): string | null {
  if (turn.phase === "rebuttal" && turn.side !== humanSide) return CUT_IN_TEXT.rebuttal;
  return null;
}
