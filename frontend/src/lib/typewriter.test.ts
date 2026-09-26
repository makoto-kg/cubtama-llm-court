import { describe, expect, it } from "vitest";

import { nextVisibleLength } from "./typewriter";

describe("nextVisibleLength", () => {
  it("一定の速さで進み、目標を超えない", () => {
    expect(nextVisibleLength(0, 50, 100, 40)).toBe(4);
    expect(nextVisibleLength(98, 100, 1000, 40)).toBe(100);
    expect(nextVisibleLength(100, 100, 100)).toBe(100);
  });

  it("大きく遅れていると加速する", () => {
    expect(nextVisibleLength(0, 1000, 100, 40)).toBe(24);
    expect(nextVisibleLength(0, 150, 100, 40)).toBe(8);
  });

  it("経過時間が短くても最低 1 文字は進む", () => {
    expect(nextVisibleLength(0, 10, 1, 40)).toBe(1);
  });

  it("目標が縮んだら目標に合わせる", () => {
    expect(nextVisibleLength(50, 10, 16)).toBe(10);
  });
});
