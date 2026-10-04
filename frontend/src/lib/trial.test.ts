import { describe, expect, it } from "vitest";

import type { DebateEvent, Explanation, TrialOption } from "@/api/client";

import {
  appendWitnessToken,
  cutInForTrialEvent,
  objectionTargets,
  focusLine,
  optionsByLine,
  pendingCollapse,
  prosecutorLine,
  shownPenaltyGauge,
  stepLine,
  testimonyExamined,
} from "./trial";
import { makePack } from "./offline/__fixtures__/pack";
import { apply, start, toTrialView } from "./offline/engine";

const option = (id: string, kind: "present" | "probe", lineId: string): TrialOption => ({
  id,
  kind,
  line_id: lineId,
  evidence_id: kind === "present" ? "CE-01" : null,
  label: id,
  strength: null,
  contradiction_id: null,
  trap_reason: null,
});

describe("appendWitnessToken", () => {
  it("同じ証人なら続けて足し、別の証人なら始め直す", () => {
    const a = appendWitnessToken(null, { witness_id: "P-02", text: "そ" });
    const b = appendWitnessToken(a, { witness_id: "P-02", text: "んな" });
    expect(b).toEqual({ witnessId: "P-02", text: "そんな" });
    expect(appendWitnessToken(b, { witness_id: "P-03", text: "私" })).toEqual({
      witnessId: "P-03",
      text: "私",
    });
  });
});

describe("cutInForTrialEvent", () => {
  it("つきつけ・ゆさぶりで文言が変わる。証言の崩壊ではイベントからは出さない", () => {
    const made = (o: TrialOption) =>
      ({ type: "trial_choice_made", option: o, session_id: "s", seq: 1 }) as unknown as DebateEvent;
    expect(cutInForTrialEvent(made(option("a", "present", "L1")))).toBe("反証!");
    expect(cutInForTrialEvent(made(option("b", "probe", "L1")))).toBe("確認!");
    // 猫言葉の検察官は、つきつけるとき「異議ありにゃ！」
    expect(cutInForTrialEvent(made(option("a", "present", "L1")), "cat")).toBe("異議ありにゃ！");
    expect(cutInForTrialEvent(made(option("b", "probe", "L1")), "cat")).toBe("確認!");
    const solved = { type: "contradiction_solved", contradiction_id: "X-01" } as unknown as DebateEvent;
    expect(cutInForTrialEvent(solved)).toBeNull();
    const other = { type: "penalty_applied" } as unknown as DebateEvent;
    expect(cutInForTrialEvent(other)).toBeNull();
  });
});

describe("optionsByLine", () => {
  it("証言の行の順にまとめ、選択肢のない行は除く", () => {
    const groups = optionsByLine(
      ["L1", "L2", "L3"],
      [option("1", "present", "L3"), option("2", "probe", "L1"), option("3", "present", "L1")],
    );
    expect(groups.map((g) => [g.lineId, g.options.map((o) => o.id)])).toEqual([
      ["L1", ["2", "3"]],
      ["L3", ["1"]],
    ]);
  });
});

describe("objectionTargets", () => {
  it("矛盾・罠・学習ポイントを指せる", () => {
    const explanation = {
      title: "t",
      truth: "",
      question: "",
      answer: "",
      items: [
        {
          contradiction_id: "X-01",
          witness_name: "w",
          testimony_line_id: "TS-01-2",
          testimony_line: "行",
          evidence_id: "CE-01",
          evidence_name: "速報",
          explanation: "",
          learning_point_ids: ["LP-01"],
          traps: [
            {
              evidence_id: "CE-03",
              evidence_name: "議事録",
              reasoning: "",
              why_tempting: "",
              learning_point_id: "LP-01",
              misconception: "",
            },
          ],
        },
      ],
      learning_points: [
        { id: "LP-01", knowledge: "知識", explanation: "", sources: [], misconception: "" },
      ],
    } as unknown as Explanation;
    expect(objectionTargets(explanation).map((t) => `${t.kind}:${t.id}`)).toEqual([
      "contradiction:X-01",
      "trap:X-01/CE-03",
      "learning_point:LP-01",
    ]);
  });
});

describe("testimonyExamined", () => {
  it("いまの証言の行への行動があるときだけ true(前の証言の行動は数えない)", () => {
    let state = start(makePack(), "seed");
    expect(testimonyExamined(toTrialView(state))).toBe(false);
    const probe = state.pending.find((o) => o.kind === "probe")!;
    state = apply(state, { kind: "choose", optionId: probe.id });
    expect(testimonyExamined(toTrialView(state))).toBe(true);
    const strong = state.pending.find((o) => o.strength === "strong")!;
    state = apply(state, { kind: "choose", optionId: strong.id });
    expect(state.testimonyId).toBe("TS-02");
    expect(testimonyExamined(toTrialView(state))).toBe(false);
  });
});

describe("focusLine / stepLine", () => {
  const lines = ["L1", "L2", "L3"];

  it("前の行が今の証言にあれば保ち、なければ選択肢のある最初の行を指す", () => {
    expect(focusLine(lines, [{ lineId: "L2" }], "L3")).toBe("L3");
    expect(focusLine(lines, [{ lineId: "L2" }], "X9")).toBe("L2");
    expect(focusLine(lines, [], null)).toBe("L1");
    expect(focusLine([], [], null)).toBeNull();
  });

  it("前後に送り、端では反対の端へ回る", () => {
    expect(stepLine(lines, "L1", 1)).toBe("L2");
    expect(stepLine(lines, "L3", 1)).toBe("L1");
    expect(stepLine(lines, "L1", -1)).toBe("L3");
    expect(stepLine(lines, null, 1)).toBe("L2");
    expect(stepLine([], "L1", 1)).toBeNull();
  });
});

describe("pendingCollapse", () => {
  const ex = (...solved: boolean[]) => solved.map((s) => ({ solved: s }));

  it("最新の応答が崩れた応答で、まだ見せていなければその番号", () => {
    expect(pendingCollapse(ex(false, true), 0)).toBe(1);
    expect(pendingCollapse(ex(false, true), 1)).toBeNull();
  });

  it("最新の応答が崩れていなければ出さない", () => {
    expect(pendingCollapse(ex(true, false), 0)).toBeNull();
    expect(pendingCollapse([], -1)).toBeNull();
  });
});

describe("prosecutorLine", () => {
  it("ゆさぶるは証言の行を引いて説明を求める", () => {
    const text = prosecutorLine(option("p", "probe", "L1"), "昨日は家にいました", null, 0);
    expect(text).toContain("昨日は家にいました");
  });

  it("つきつけるは証拠品の名前を出す。手番で言い回しが変わる", () => {
    const present = option("e", "present", "L1");
    const a = prosecutorLine(present, "昨日は家にいました", "日程表", 0);
    const b = prosecutorLine(present, "昨日は家にいました", "日程表", 1);
    expect(a).toContain("日程表");
    expect(b).toContain("日程表");
    expect(a).not.toBe(b);
    expect(prosecutorLine(present, "昨日は家にいました", "日程表", 3)).toBe(a);
  });

  it("長い証言の行は切り詰めて引く", () => {
    const text = prosecutorLine(option("p", "probe", "L1"), "あ".repeat(50), null, 0);
    expect(text).toContain(`${"あ".repeat(27)}…`);
  });
});

describe("prosecutorLine の口調", () => {
  it("猫言葉の事件では、どの言い回しも「にゃ」で話す", () => {
    for (const kind of ["probe", "present"] as const) {
      for (const n of [0, 1, 2]) {
        const text = prosecutorLine(option("x", kind, "L1"), "昨日は家にいました", "日程表", n, "cat");
        expect(text).toContain("にゃ");
      }
    }
    expect(prosecutorLine(option("x", "probe", "L1"), "昨日は家にいました", null, 0)).not.toContain("にゃ");
    // つきつけるときは「異議ありにゃ！」から始める(ゆさぶるでは言わない)
    for (const n of [0, 1, 2]) {
      expect(prosecutorLine(option("x", "present", "L1"), "昨日", "日程表", n, "cat")).toMatch(/^異議ありにゃ！/);
      expect(prosecutorLine(option("x", "probe", "L1"), "昨日", null, n, "cat")).not.toContain("異議あり");
    }
  });
});

describe("shownPenaltyGauge", () => {
  it("選んだ行動への応答を読み終えるまでは、選ぶ前の値を見せる", () => {
    const choice = { index: 3, gauge: 5 };
    expect(shownPenaltyGauge(3, choice, null)).toBe(5);
    expect(shownPenaltyGauge(3, choice, "r-2")).toBe(5);
  });

  it("応答を読み終えたら実際の値", () => {
    expect(shownPenaltyGauge(3, { index: 3, gauge: 5 }, "r-3")).toBe(3);
  });

  it("この画面で選んだ行動がなければ実際の値", () => {
    expect(shownPenaltyGauge(3, null, null)).toBe(3);
  });
});
