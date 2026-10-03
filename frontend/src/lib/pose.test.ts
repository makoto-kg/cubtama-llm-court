import { describe, expect, it } from "vitest";

import { defendantPose, prosecutorPose } from "./pose";

describe("prosecutorPose", () => {
  it("つきつけるときは決めのポーズ", () => {
    expect(prosecutorPose({ kind: "present" })).toBe("igiari");
  });

  it("ゆさぶるとき・選んでいないときは通常", () => {
    expect(prosecutorPose({ kind: "probe" })).toBe("standard");
    expect(prosecutorPose(null)).toBe("standard");
  });
});

describe("defendantPose", () => {
  it("証拠品をつきつけられたら困惑する(強さが伏せてあっても)", () => {
    expect(defendantPose({ kind: "present", strength: "strong" })).toBe("nervous");
    expect(defendantPose({ kind: "present", strength: "weak" })).toBe("nervous");
    expect(defendantPose({ kind: "present", strength: null })).toBe("nervous");
    expect(defendantPose({ kind: "present" })).toBe("nervous");
  });

  it("的外れな証拠品・ゆさぶり・応答がないときは通常", () => {
    expect(defendantPose({ kind: "present", strength: "trap" })).toBe("standard");
    expect(defendantPose({ kind: "probe", strength: null })).toBe("standard");
    expect(defendantPose(null)).toBe("standard");
  });
});
