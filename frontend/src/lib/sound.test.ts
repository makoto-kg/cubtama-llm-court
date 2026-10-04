import { describe, expect, it } from "vitest";

import { BLIP_INTERVAL_MS, blipDue, parseSoundEnabled } from "./sound";

describe("blipDue", () => {
  it("声を出す文字が出て、間隔があいていれば鳴らす", () => {
    expect(blipDue("にゃ", BLIP_INTERVAL_MS)).toBe(true);
    expect(blipDue("a", 1000)).toBe(true);
  });

  it("前に鳴らしてから間隔が短ければ鳴らさない", () => {
    expect(blipDue("にゃ", BLIP_INTERVAL_MS - 1)).toBe(false);
  });

  it("空白・句読点・記号だけなら鳴らさない", () => {
    expect(blipDue("、", 1000)).toBe(false);
    expect(blipDue("……!", 1000)).toBe(false);
    expect(blipDue(" 「", 1000)).toBe(false);
    expect(blipDue("", 1000)).toBe(false);
  });

  it("句読点と文字がまざっていれば鳴らす", () => {
    expect(blipDue("。で", 1000)).toBe(true);
  });
});

describe("parseSoundEnabled", () => {
  it("既定は音を出さない。on のときだけ出す", () => {
    expect(parseSoundEnabled(null)).toBe(false);
    expect(parseSoundEnabled("on")).toBe(true);
    expect(parseSoundEnabled("broken")).toBe(false);
    expect(parseSoundEnabled("off")).toBe(false);
  });
});
