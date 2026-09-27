import { describe, expect, it } from "vitest";

import { createRandom, shuffle } from "./prng";

describe("prng", () => {
  it("同じ seed なら同じ列、別の seed なら別の列", () => {
    const a = createRandom("s");
    const b = createRandom("s");
    const seqA = [a(), a(), a()];
    expect([b(), b(), b()]).toEqual(seqA);
    expect(seqA.every((x) => x >= 0 && x < 1)).toBe(true);
    const c = createRandom("t");
    expect(c()).not.toBe(seqA[0]);
  });

  it("shuffle は要素を保ち、元の配列を変えない", () => {
    const items = [1, 2, 3, 4, 5, 6];
    const shuffled = shuffle(items, createRandom("x"));
    expect([...shuffled].sort()).toEqual(items);
    expect(items).toEqual([1, 2, 3, 4, 5, 6]);
    expect(shuffle(items, createRandom("x"))).toEqual(shuffled);
  });
});
