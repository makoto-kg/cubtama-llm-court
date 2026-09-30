import { describe, expect, it } from "vitest";

import { isAdvanceKey } from "./keys";

const doc = (modal: boolean) => ({ querySelector: () => (modal ? ({} as Element) : null) });

describe("isAdvanceKey", () => {
  it("Enter・Space で台詞を送る", () => {
    expect(isAdvanceKey({ key: "Enter" }, doc(false))).toBe(true);
    expect(isAdvanceKey({ key: " " }, doc(false))).toBe(true);
    expect(isAdvanceKey({ key: "a" }, doc(false))).toBe(false);
  });

  it("ダイアログが開いているときは送らない", () => {
    expect(isAdvanceKey({ key: "Enter" }, doc(true))).toBe(false);
  });
});
