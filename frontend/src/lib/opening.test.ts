import { describe, expect, it } from "vitest";

import { start, toTrialView } from "./offline/engine";
import { makePack } from "./offline/__fixtures__/pack";
import { briefOverview, defendantOf, OPENING_CUT_IN, openingScript, shouldShowOpening } from "./opening";

describe("briefOverview", () => {
  it("最初の 1 文だけを取り出す", () => {
    expect(briefOverview(" 調査会議の件。各委員は異なる見解を示した。")).toBe("調査会議の件。");
    expect(briefOverview("句点のない概要")).toBe("句点のない概要");
  });

  it("長すぎる文は切り詰める", () => {
    expect(briefOverview("あ".repeat(100), 10)).toBe(`${"あ".repeat(9)}…`);
  });
});

describe("openingScript", () => {
  it("裁判長の挨拶と概要 → 原告・被告の宣言 → 審理開始の順になる", () => {
    const view = toTrialView(start(makePack(), "seed"));
    const script = openingScript(view);
    expect(script.map((l) => l.speaker)).toEqual([
      "judge",
      "judge",
      "judge",
      "plaintiff",
      "judge",
      "defendant",
      "judge",
    ]);
    expect(script[0].cutIn).toBe(OPENING_CUT_IN.open);
    expect(script[0].text).toContain(view.case.title);
    expect(script[1].text).toContain(briefOverview(view.case.overview));
  });

  it("最初に呼ぶ証人は、いま尋問する証言の証人(矛盾のない証言は飛ばす)", () => {
    const view = toTrialView(start(makePack(), "seed"));
    const witness = view.case.people.find((p) => p.id === "P-02")!.name;
    expect(openingScript(view).at(-1)!.text).toContain(witness);
  });

  it("役割が「被告」の人物がいれば、概要の後で裁判長が被告を紹介する", () => {
    const view = toTrialView(start(makePack(), "seed"));
    const people = view.case.people.map((p, i) => (i === 0 ? { ...p, role: "被告(茶トラ猫)" } : p));
    const script = openingScript({ ...view, case: { ...view.case, people } });
    expect(script).toHaveLength(8);
    expect(script[2]).toEqual({
      speaker: "judge",
      text: `被告は、${people[0].name}。${people[0].description}`,
    });
    expect(defendantOf(view)).toBeNull();
  });
});

describe("shouldShowOpening", () => {
  it("尋問が始まる前だけ見せる", () => {
    const view = toTrialView(start(makePack(), "seed"));
    expect(shouldShowOpening(view)).toBe(true);
    expect(shouldShowOpening({ ...view, status: "finished" })).toBe(false);
    expect(shouldShowOpening({ ...view, exchanges: [{} as (typeof view.exchanges)[number]] })).toBe(false);
  });
});
