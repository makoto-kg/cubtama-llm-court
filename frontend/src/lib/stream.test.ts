import { describe, expect, it } from "vitest";

import { appendToken, startTurn, turnId } from "./stream";

const aff = { phase: "opening" as const, round: 0, side: "affirmative" as const };
const neg = { phase: "opening" as const, round: 0, side: "negative" as const };

describe("appendToken", () => {
  it("同じ手番のトークンをつなぐ", () => {
    let s = startTurn(aff);
    s = appendToken(s, { ...aff, text: "導入" });
    s = appendToken(s, { ...aff, text: "すべき" });
    expect(s.text).toBe("導入すべき");
  });

  it("別の手番のトークンは新しい発言として始める", () => {
    const s = appendToken({ ...aff, text: "前の発言" }, { ...neg, text: "反対" });
    expect(s).toEqual({ ...neg, text: "反対" });
    expect(turnId(s)).toBe("opening-0-negative");
  });

  it("turn より先にトークンが届いても発言を始める", () => {
    expect(appendToken(null, { ...aff, text: "a" }).text).toBe("a");
  });
});
