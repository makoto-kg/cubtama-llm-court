import { describe, expect, it } from "vitest";

import type { OfflineState } from "./engine";
import { apply, OfflineActionError, replay, start, toTrialView, type OfflineAction } from "./engine";
import { availableEvidenceIds } from "./analyst";
import { makePack } from "./__fixtures__/pack";

function pick(state: OfflineState, strength: string | null, kind = "present"): OfflineAction {
  const option = state.pending.find((o) => o.kind === kind && (o.strength ?? null) === strength);
  if (!option) throw new Error(`no ${kind} ${strength}`);
  return { kind: "choose", optionId: option.id };
}

describe("offline engine", () => {
  it("矛盾のない証言を飛ばし、最初の証言の選択肢を用意する", () => {
    const state = start(makePack(), "seed");
    expect(state.testimonyId).toBe("TS-01");
    expect(state.pending.length).toBeGreaterThan(0);
    const view = toTrialView(state);
    expect(view.stage).toBe("choosing");
    expect(view.pending_options.every((o) => o.strength == null && o.contradiction_id == null)).toBe(true);
    expect(view.explanation).toBeNull();
  });

  it("最初から解説まで進み、行動の列から同じ状態を再現できる", () => {
    const pack = makePack();
    const actions: OfflineAction[] = [];
    let state = start(pack, "seed");
    const step = (action: OfflineAction) => {
      actions.push(action);
      state = apply(state, action);
    };

    step(pick(state, null, "probe"));
    expect(state.exchanges[0].text).toMatch(/^言い逃れ/);
    expect(state.gauge).toBe(5);

    step(pick(state, "trap"));
    expect(state.gauge).toBe(3);
    expect(state.exchanges[1].penalty).toBe(2);

    step(pick(state, "strong"));
    expect(state.solved).toEqual(["X-01"]);
    expect(state.exchanges[2].text).toBe("崩れた(present:TS-01-2:CE-01)");
    expect(state.testimonyId).toBe("TS-02");

    // 全矛盾を解いたら、最後の問いを出さずに閉廷する(ADR 0020)
    step(pick(state, "strong"));
    const view = toTrialView(state);
    expect(view.solved_line_ids).toEqual(["TS-01-2", "TS-02-2"]);
    expect(view.result).toBe("solved");
    expect(view.status).toBe("finished");
    expect(view.answer_index).toBeNull();
    expect(view.explanation?.answer).toBe("担当者");
    expect(view.exchanges[0].check).not.toBeNull(); // 閉廷後は判定を公開

    step({ kind: "object", targetKind: "contradiction", targetId: "X-01", comment: "解説が短い", at: "2026-09-27T00:00:00Z" });
    expect(toTrialView(state).objections.map((o) => o.target_id)).toEqual(["X-01"]);

    const replayed = replay(pack, "seed", actions);
    expect(toTrialView(replayed)).toEqual(toTrialView(state));
  });

  it("ゲージが尽きたら閉廷する", () => {
    let state = start(makePack(2), "seed");
    state = apply(state, pick(state, "trap"));
    expect(state.result).toBe("penalty");
    expect(state.pending).toEqual([]);
    expect(() => apply(state, pick(start(makePack(2), "seed"), "strong"))).toThrow(OfflineActionError);
  });

  it("手順違反は OfflineActionError", () => {
    const state = start(makePack(), "seed");
    expect(() => apply(state, { kind: "choose", optionId: "nothing" })).toThrow(OfflineActionError);
    expect(() => apply(state, { kind: "answer", index: 1 })).toThrow(OfflineActionError);
    expect(() =>
      apply(state, { kind: "object", targetKind: "contradiction", targetId: "X-01", comment: "x", at: "" }),
    ).toThrow(OfflineActionError);
  });

  it("別の seed では選択肢の並びが変わりうるが、同じ seed では同じ", () => {
    expect(start(makePack(), "a").pending).toEqual(start(makePack(), "a").pending);
  });
});

describe("尋問の中で手に入る証拠品(ADR 0019)", () => {
  // X-02 の正解の証拠品 CE-02 は、TS-02-1 をゆさぶると手に入る
  const locked = () => makePack(5, [{ evidence_id: "CE-02", kind: "probe", line_id: "TS-02-1" }]);

  it("手に入れるまで、法廷記録に出さず、つきつける選択肢にも並べない", () => {
    let state = start(locked(), "seed");
    expect(toTrialView(state).case.evidence.map((e) => e.id)).not.toContain("CE-02");
    expect(availableEvidenceIds(state.pack, state.tried).has("CE-02")).toBe(false);

    const strong = state.pending.find((o) => o.strength === "strong")!;
    state = apply(state, { kind: "choose", optionId: strong.id });
    expect(state.testimonyId).toBe("TS-02");
    expect(state.pending.some((o) => o.evidence_id === "CE-02")).toBe(false);
    expect(state.pending.some((o) => o.contradiction_id === "X-02")).toBe(false);
    // 手に入れる行動(ゆさぶる)は必ず並ぶ
    const probe = state.pending.find((o) => o.kind === "probe" && o.line_id === "TS-02-1");
    expect(probe).toBeDefined();

    state = apply(state, { kind: "choose", optionId: probe!.id });
    expect(toTrialView(state).case.evidence.map((e) => e.id)).toContain("CE-02");
    expect(state.pending.some((o) => o.contradiction_id === "X-02" && o.evidence_id === "CE-02")).toBe(true);
  });

  it("手に入れた証拠品は、行動の列から作り直しても手元にある", () => {
    const pack = locked();
    const actions: OfflineAction[] = [];
    let state = start(pack, "seed");
    for (const pickOption of [
      (s: OfflineState) => s.pending.find((o) => o.strength === "strong")!,
      (s: OfflineState) => s.pending.find((o) => o.kind === "probe" && o.line_id === "TS-02-1")!,
    ]) {
      const action: OfflineAction = { kind: "choose", optionId: pickOption(state).id };
      actions.push(action);
      state = apply(state, action);
    }
    expect(toTrialView(replay(pack, "seed", actions)).case.evidence.map((e) => e.id)).toContain("CE-02");
  });
});

describe("以前の保存データ", () => {
  it("最後の問いに答えた行動は、全矛盾を解いて閉廷したあとなので読み飛ばす", () => {
    const pack = makePack();
    let state = start(pack, "seed");
    const actions: OfflineAction[] = [];
    while (state.result === null) {
      const action: OfflineAction = { kind: "choose", optionId: state.pending.find((o) => o.strength === "strong")!.id };
      actions.push(action);
      state = apply(state, action);
    }
    const replayed = replay(pack, "seed", [...actions, { kind: "answer", index: 1 }]);
    expect(replayed.result).toBe("solved");
    expect(replayed.answerIndex).toBeNull();
  });
});
