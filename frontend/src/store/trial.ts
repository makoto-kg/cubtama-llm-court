import { create } from "zustand";

import type { DebateEvent, TrialView } from "@/api/client";
import { mergeEvents } from "@/lib/events";
import { appendWitnessToken, type WitnessStream } from "@/lib/trial";

import type { TaskNotice } from "./court";

/**
 * 裁判画面の表示用の状態。ゲーム状態の真実はバックエンドのイベントログで、
 * ここには API から受け取ったものと、そこから導いた表示用の派生状態だけを置く。
 */
type TrialStoreState = {
  sessionId: string | null;
  view: TrialView | null;
  events: DebateEvent[];
  streaming: WitnessStream | null;
  progress: string | null;
  task: TaskNotice | null;
  cutIn: { text: string; key: number; strong: boolean } | null;
  error: string | null;

  reset: (sessionId: string) => void;
  setView: (view: TrialView) => void;
  addEvents: (events: DebateEvent[]) => void;
  startWitness: (witnessId: string) => void;
  appendToken: (token: { witness_id: string; text: string }) => void;
  endStreaming: () => void;
  setProgress: (message: string | null) => void;
  setTask: (task: TaskNotice) => void;
  showCutIn: (text: string, strong?: boolean) => void;
  clearCutIn: () => void;
  setError: (error: string | null) => void;
};

export const useTrialStore = create<TrialStoreState>((set) => ({
  sessionId: null,
  view: null,
  events: [],
  streaming: null,
  progress: null,
  task: null,
  cutIn: null,
  error: null,

  reset: (sessionId) =>
    set({
      sessionId,
      view: null,
      events: [],
      streaming: null,
      progress: null,
      task: null,
      cutIn: null,
      error: null,
    }),
  setView: (view) => set({ view }),
  addEvents: (events) => set((s) => ({ events: mergeEvents(s.events, events) })),
  startWitness: (witnessId) => set({ streaming: { witnessId, text: "" }, progress: null }),
  appendToken: (token) => set((s) => ({ streaming: appendWitnessToken(s.streaming, token) })),
  endStreaming: () => set({ streaming: null }),
  setProgress: (progress) => set({ progress }),
  setTask: (task) => set({ task }),
  showCutIn: (text, strong = false) => set({ cutIn: { text, key: Date.now(), strong } }),
  clearCutIn: () => set({ cutIn: null }),
  setError: (error) => set({ error }),
}));
