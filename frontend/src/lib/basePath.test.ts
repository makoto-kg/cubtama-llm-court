import { describe, expect, it } from "vitest";
import { withBasePath } from "./basePath";

describe("withBasePath", () => {
  it("接頭辞が空ならそのまま返す", () => {
    expect(withBasePath("/assets/judge.svg", "")).toBe("/assets/judge.svg");
  });

  it("接頭辞を前に付ける", () => {
    expect(withBasePath("/offline/index.json", "/llm-court")).toBe("/llm-court/offline/index.json");
  });
});
