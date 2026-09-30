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
  it("裁判官の挨拶・概要・被告の紹介 → 検察官と被告の宣言 → 審理開始の順になる", () => {
    const view = toTrialView(start(makePack(), "seed"));
    const script = openingScript(view);
    expect(script.map((l) => l.speaker)).toEqual([
      "judge",
      "judge",
      "judge",
      "judge",
      "prosecutor",
      "judge",
      "defendant",
      "judge",
    ]);
    expect(script[0].cutIn).toBe(OPENING_CUT_IN.open);
    expect(script[0].text).toContain(view.case.title);
    expect(script[1].text).toContain(briefOverview(view.case.overview));
  });

  it("被告は事件の defendant_id で決まり、裁判官が紹介して証言台に呼ぶ", () => {
    const view = toTrialView(start(makePack(), "seed"));
    const defendant = defendantOf(view)!;
    expect(defendant.id).toBe(view.case.defendant_id);
    const script = openingScript(view);
    expect(script[2].text).toBe(`被告は、${defendant.name}。${defendant.description}`);
    expect(script[5].text).toContain(defendant.name);
  });

  it("被告のない旧形式の事件は、紹介を省き、最初に証言する人を証言台に呼ぶ", () => {
    const view = toTrialView(start(makePack(), "seed"));
    const people = view.case.people.map((p) => ({ ...p, role: "関係者" }));
    const old = { ...view, case: { ...view.case, defendant_id: null, people } };
    expect(defendantOf(old)).toBeNull();
    const script = openingScript(old);
    expect(script).toHaveLength(7);
    const speaker = people.find((p) => p.id === view.case.testimonies[1].witness_id)!;
    expect(script[4].text).toContain(speaker.name);
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

describe("検察官の宣言の口調", () => {
  it("猫言葉の事件では「にゃ」で宣言する", () => {
    const view = toTrialView(start(makePack(), "seed"));
    const prosecutor = (v: typeof view) => openingScript(v).find((l) => l.speaker === "prosecutor")!.text;
    expect(prosecutor(view)).not.toContain("にゃ");
    expect(prosecutor({ ...view, case: { ...view.case, prosecutor_speech: "cat" } })).toContain("にゃ");
  });
});
