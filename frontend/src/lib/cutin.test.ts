import { describe, expect, it } from "vitest";

import type { ChoiceOption } from "@/api/client";
import { CUT_IN_TEXT, cutInForChoice, cutInForTurn } from "./cutin";

function option(kind: ChoiceOption["kind"]): ChoiceOption {
  return { id: "T01-1", kind, label: "見出し", pitch: "要旨", source: null };
}

describe("cutIn", () => {
  it("選択肢の種類で文言が決まる", () => {
    expect(cutInForChoice(option("contradiction"))).toBe(CUT_IN_TEXT.contradiction);
    expect(cutInForChoice(option("probe"))).toBe(CUT_IN_TEXT.probe);
    expect(cutInForChoice(option("argument"))).toBeNull();
  });

  it("LLM 側の反論の開始時だけ出す", () => {
    const rebuttal = { phase: "rebuttal" as const, round: 1, side: "affirmative" as const };
    expect(cutInForTurn(rebuttal, "negative")).toBe(CUT_IN_TEXT.rebuttal);
    expect(cutInForTurn(rebuttal, "affirmative")).toBeNull();
    expect(cutInForTurn({ ...rebuttal, phase: "opening" }, null)).toBeNull();
    expect(cutInForTurn(rebuttal, null)).toBe(CUT_IN_TEXT.rebuttal);
  });
});
