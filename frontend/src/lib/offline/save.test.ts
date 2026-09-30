import { describe, expect, it } from "vitest";

import { hasProgress, parseSave, revealSteps } from "./save";

describe("parseSave", () => {
  it("正しい形だけを受け付ける", () => {
    expect(parseSave(null)).toBeNull();
    expect(parseSave("{壊れた")).toBeNull();
    expect(parseSave(JSON.stringify({ seed: 1, actions: [] }))).toBeNull();
    const save = { seed: "s", actions: [{ kind: "answer", index: 0 }] };
    expect(parseSave(JSON.stringify(save))).toEqual(save);
  });
});

describe("revealSteps", () => {
  it("少しずつ伸ばし、最後は全文", () => {
    expect(revealSteps("abcdefghij", 4)).toEqual(["abcd", "abcdefgh", "abcdefghij"]);
    expect(revealSteps("ab", 4)).toEqual(["ab"]);
  });
});

describe("hasProgress", () => {
  it("行動が 1 つ以上ある保存データだけを「続き」とみなす", () => {
    expect(hasProgress(null)).toBe(false);
    expect(hasProgress({ seed: "s", actions: [] })).toBe(false);
    expect(hasProgress({ seed: "s", actions: [{ kind: "answer", index: 0 }] })).toBe(true);
  });
});
