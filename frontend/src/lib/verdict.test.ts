import { describe, expect, it } from "vitest";

import { apply, start, toTrialView } from "./offline/engine";
import { makePack } from "./offline/__fixtures__/pack";
import { DEFAULT_VERDICT, hasVerdictScene, VERDICT_CUT_IN, verdictScript } from "./verdict";

function solvedView(verdict?: { sentence: string; defendant_reaction: string }) {
  const pack = makePack();
  const withVerdict = verdict ? { ...pack, explanation: { ...pack.explanation, verdict } } : pack;
  let state = start(withVerdict, "seed");
  while (state.result === null) {
    state = apply(state, { kind: "choose", optionId: state.pending.find((o) => o.strength === "strong")!.id });
  }
  return toTrialView(state);
}

describe("verdictScript", () => {
  it("裁判官が有罪と刑罰を言い渡し、最後に被告が反応する", () => {
    const view = solvedView({ sentence: "3日間のおやつ抜き", defendant_reaction: "にゃんですと……" });
    const script = verdictScript(view);
    expect(script.map((l) => l.speaker)).toEqual(["judge", "judge", "judge", "defendant"]);
    expect(script[0].cutIn).toBe(VERDICT_CUT_IN.verdict);
    expect(script[1].text).toContain("白波 恵");
    expect(script[1].text).toContain("有罪");
    expect(script[2].text).toContain("3日間のおやつ抜き");
    expect(script[3].text).toBe("にゃんですと……");
    expect(script[3].pose).toBe("lose");
  });

  it("事件に判決のデータがなければ定型文", () => {
    const script = verdictScript(solvedView());
    expect(script[2].text).not.toContain("「");
    expect(script[3].text).toBe(DEFAULT_VERDICT.defendant_reaction);
  });
});

describe("hasVerdictScene", () => {
  it("全矛盾を解いて閉廷したときだけ", () => {
    expect(hasVerdictScene(solvedView())).toBe(true);
    let state = start(makePack(2), "seed");
    state = apply(state, { kind: "choose", optionId: state.pending.find((o) => o.strength === "trap")!.id });
    expect(toTrialView(state).result).toBe("penalty");
    expect(hasVerdictScene(toTrialView(state))).toBe(false);
  });
});
