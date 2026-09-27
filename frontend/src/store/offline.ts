import { create } from "zustand";

import type { OfflinePack } from "@/api/client";
import { apply, type OfflineAction, type OfflineState, replay } from "@/lib/offline/engine";
import { clearSave, loadSave, revealSteps, writeSave } from "@/lib/offline/save";
import { COLLAPSE_CUT_IN, cutInForTrialChoice, type WitnessStream } from "@/lib/trial";

const REVEAL_INTERVAL_MS = 30;

function newSeed(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID().slice(0, 12)
    : Math.random().toString(36).slice(2, 14);
}

/**
 * オフラインの裁判の表示用の状態。真実は `localStorage` の行動の列で、状態はそこから再生する。
 * 証人の応答は事前シミュレーションの結果を、少しずつ表示して「流れる」ように見せる。
 */
type OfflineStoreState = {
  caseId: string | null;
  pack: OfflinePack | null;
  seed: string;
  actions: OfflineAction[];
  state: OfflineState | null;
  streaming: WitnessStream | null;
  cutIn: { text: string; key: number; strong: boolean } | null;
  error: string | null;

  load: (caseId: string, pack: OfflinePack) => void;
  setError: (error: string | null) => void;
  choose: (optionId: string) => void;
  answer: (index: number) => void;
  object: (targetKind: Extract<OfflineAction, { kind: "object" }>["targetKind"], targetId: string, comment: string) => void;
  restart: () => void;
  clearCutIn: () => void;
};

let timer: ReturnType<typeof setInterval> | null = null;

function stopReveal() {
  if (timer) clearInterval(timer);
  timer = null;
}

export const useOfflineStore = create<OfflineStoreState>((set, get) => {
  /** 行動を適用して保存する。失敗したら状態を変えずにエラーを出す。 */
  const commit = (action: OfflineAction): OfflineState | null => {
    const { state, caseId, seed, actions } = get();
    if (!state || !caseId) return null;
    try {
      const nextState = apply(state, action);
      const nextActions = [...actions, action];
      writeSave(caseId, { seed, actions: nextActions });
      set({ actions: nextActions, error: null });
      return nextState;
    } catch (e) {
      set({ error: e instanceof Error ? e.message : String(e) });
      return null;
    }
  };

  return {
    caseId: null,
    pack: null,
    seed: "",
    actions: [],
    state: null,
    streaming: null,
    cutIn: null,
    error: null,

    load: (caseId, pack) => {
      stopReveal();
      const saved = loadSave(caseId);
      let seed = saved?.seed ?? newSeed();
      let actions = saved?.actions ?? [];
      let state: OfflineState;
      try {
        state = replay(pack, seed, actions);
      } catch {
        // パックが更新されて保存データを再生できない場合は最初から
        seed = newSeed();
        actions = [];
        state = replay(pack, seed, actions);
      }
      writeSave(caseId, { seed, actions });
      set({ caseId, pack, seed, actions, state, streaming: null, cutIn: null, error: null });
    },
    setError: (error) => set({ error }),

    choose: (optionId) => {
      if (get().streaming) return;
      const option = get().state?.pending.find((o) => o.id === optionId);
      const nextState = commit({ kind: "choose", optionId });
      if (!nextState || !option) return;
      const exchange = nextState.exchanges.at(-1)!;
      set({ cutIn: { text: cutInForTrialChoice(option), key: Date.now(), strong: false } });
      const steps = revealSteps(exchange.text);
      let i = 0;
      set({ streaming: { witnessId: exchange.witness_id, text: "" } });
      stopReveal();
      timer = setInterval(() => {
        if (i < steps.length) {
          set({ streaming: { witnessId: exchange.witness_id, text: steps[i++] } });
          return;
        }
        stopReveal();
        set({ streaming: null, state: nextState });
        if (exchange.solved) set({ cutIn: { text: COLLAPSE_CUT_IN, key: Date.now(), strong: true } });
      }, REVEAL_INTERVAL_MS);
    },
    answer: (index) => {
      const nextState = commit({ kind: "answer", index });
      if (nextState) set({ state: nextState });
    },
    object: (targetKind, targetId, comment) => {
      const nextState = commit({ kind: "object", targetKind, targetId, comment, at: new Date().toISOString() });
      if (nextState) set({ state: nextState });
    },
    restart: () => {
      const { caseId, pack } = get();
      if (!caseId || !pack) return;
      clearSave(caseId);
      get().load(caseId, pack);
    },
    clearCutIn: () => set({ cutIn: null }),
  };
});
