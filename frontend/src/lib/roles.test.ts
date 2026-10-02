import { describe, expect, it } from "vitest";

import { start, toTrialView } from "./offline/engine";
import { makePack } from "./offline/__fixtures__/pack";
import { defendantLabel, judgeLabel, prosecutorLabel, speakerLabel } from "./roles";

const view = () => toTrialView(start(makePack(), "seed"));

describe("名札", () => {
  it("裁判官は「アヤ裁判長」", () => {
    expect(judgeLabel()).toBe("アヤ裁判長");
  });

  it("被告は「名前被告」、それ以外の人物は名前だけ", () => {
    expect(speakerLabel(view(), "P-02")).toBe("白波 恵被告");
    expect(speakerLabel(view(), "P-03")).toBe("黒川 誠");
    expect(defendantLabel(view())).toBe("白波 恵被告");
  });

  it("検察官を演じる人物がいれば「名前検察官」、いなければ「検察官（あなた）」", () => {
    const v = view();
    expect(prosecutorLabel(v)).toBe("検察官（あなた）");
    expect(prosecutorLabel({ ...v, case: { ...v.case, prosecutor_id: "P-01" } })).toBe("朝霧 透検察官");
  });
});
