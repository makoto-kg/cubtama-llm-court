import { create } from "zustand";

import type { DebateEvent, SessionView } from "@/api/client";
import { mergeEvents } from "@/lib/events";
import { appendToken, startTurn, type StreamingStatement, type TurnKey } from "@/lib/stream";

export type TaskNotice = { kind: string; status: string; error?: string };

/**
 * 法廷画面の表示用の状態。ゲーム状態の真実はバックエンドのイベントログで、
 * ここには API から受け取ったものと、そこから導いた表示用の派生状態だけを置く。
 */
type CourtState = {
  sessionId: string | null;
  view: SessionView | null;
  events: DebateEvent[];
  progress: string[];
  streaming: StreamingStatement | null;
  task: TaskNotice | null;
  cutIn: { text: string; key: number } | null;
  error: string | null;

  reset: (sessionId: string) => void;
  setView: (view: SessionView) => void;
  addEvents: (events: DebateEvent[]) => void;
  pushProgress: (message: string) => void;
  startTurn: (turn: TurnKey) => void;
  appendToken: (token: TurnKey & { text: string }) => void;
  endStreaming: () => void;
  setTask: (task: TaskNotice) => void;
  showCutIn: (text: string) => void;
  clearCutIn: () => void;
  setError: (error: string | null) => void;
};

export const useCourtStore = create<CourtState>((set) => ({
  sessionId: null,
  view: null,
  events: [],
  progress: [],
  streaming: null,
  task: null,
  cutIn: null,
  error: null,

  reset: (sessionId) =>
    set({
      sessionId,
      view: null,
      events: [],
      progress: [],
      streaming: null,
      task: null,
      cutIn: null,
      error: null,
    }),
  setView: (view) => set({ view }),
  addEvents: (events) => set((s) => ({ events: mergeEvents(s.events, events) })),
  pushProgress: (message) => set((s) => ({ progress: [...s.progress, message] })),
  startTurn: (turn) => set({ streaming: startTurn(turn) }),
  appendToken: (token) => set((s) => ({ streaming: appendToken(s.streaming, token) })),
  endStreaming: () => set({ streaming: null }),
  setTask: (task) => set({ task }),
  showCutIn: (text) => set({ cutIn: { text, key: Date.now() } }),
  clearCutIn: () => set({ cutIn: null }),
  setError: (error) => set({ error }),
}));
