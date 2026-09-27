import { describe, expect, it } from "vitest";

import { makePack } from "./__fixtures__/pack";
import { prepareOptions, triedKey } from "./analyst";

const pack = makePack();
const testimony = pack.case.testimonies[1];

describe("prepareOptions", () => {
  it("正解・罠・はずれ・ゆさぶるを並べる", () => {
    const options = prepareOptions({ pack, testimony, solved: new Set(), tried: new Set(), idPrefix: "Q01", seed: "s" });
    const strong = options.filter((o) => o.strength === "strong");
    expect(strong.map((o) => [o.line_id, o.evidence_id, o.contradiction_id])).toEqual([["TS-01-2", "CE-01", "X-01"]]);
    const traps = options.filter((o) => o.strength === "trap");
    expect(traps.map((o) => o.evidence_id)).toEqual(["CE-03"]);
    expect(traps[0].trap_reason).toBe("誤解があるから");
    expect(options.filter((o) => o.strength === "weak")).toHaveLength(2);
    expect(options.filter((o) => o.kind === "probe")).toHaveLength(2);
    expect(new Set(options.map((o) => o.id)).size).toBe(options.length);
    expect(options.every((o) => o.id.startsWith("Q01-"))).toBe(true);
    expect(strong[0].label).toContain("つきつける");
  });

  it("同じ seed なら同じ並び。選んだ行動は並べない", () => {
    const args = { pack, testimony, solved: new Set<string>(), idPrefix: "Q01", seed: "s" };
    expect(prepareOptions({ ...args, tried: new Set() })).toEqual(prepareOptions({ ...args, tried: new Set() }));
    const tried = new Set([
      triedKey({ kind: "present", line_id: "TS-01-2", evidence_id: "CE-03" }),
      triedKey({ kind: "probe", line_id: "TS-01-1" }),
    ]);
    const rest = prepareOptions({ ...args, tried });
    expect(rest.some((o) => o.strength === "trap")).toBe(false);
    expect(rest.some((o) => o.kind === "probe" && o.line_id === "TS-01-1")).toBe(false);
  });
});
