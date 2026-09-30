import { describe, expect, it } from "vitest";

import { DEFAULT_MODE, parseMode } from "./mode";

describe("parseMode", () => {
  it("既定はオフライン", () => {
    expect(DEFAULT_MODE).toBe("offline");
    expect(parseMode(null)).toBe("offline");
    expect(parseMode(undefined)).toBe("offline");
    expect(parseMode("")).toBe("offline");
    expect(parseMode("something")).toBe("offline");
  });

  it("保存したモードを読む", () => {
    expect(parseMode("online")).toBe("online");
    expect(parseMode("offline")).toBe("offline");
  });
});
