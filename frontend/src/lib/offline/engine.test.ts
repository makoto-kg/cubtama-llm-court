import { describe, expect, it } from "vitest";

import type { OfflineState } from "./engine";
import { apply, OfflineActionError, replay, start, toTrialView, type OfflineAction } from "./engine";
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

    step(pick(state, "strong"));
    let view = toTrialView(state);
    expect(view.stage).toBe("answering");
    expect(view.solved_line_ids).toEqual(["TS-01-2", "TS-02-2"]);
    expect(() => apply(state, { kind: "answer", index: 9 })).toThrow(OfflineActionError);

    step({ kind: "answer", index: 1 });
    view = toTrialView(state);
    expect(view.result).toBe("solved");
    expect(view.status).toBe("finished");
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
