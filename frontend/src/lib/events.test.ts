import { describe, expect, it } from "vitest";

import type { DebateEvent } from "@/api/client";
import { foundEvidence, isTerminal, lastSeq, llmCalls, mergeEvents } from "./events";

type PhaseEvent = Extract<DebateEvent, { type: "phase_started" }>;

function phase(seq: number, round = 0): PhaseEvent {
  return { type: "phase_started", seq, session_id: "s", phase: "opening", round };
}

describe("mergeEvents", () => {
  it("seq で重複を除き、並べ替える", () => {
    const merged = mergeEvents([phase(1), phase(3)], [phase(2), phase(3)]);
    expect(merged.map((e) => e.seq)).toEqual([1, 2, 3]);
    expect(lastSeq(merged)).toBe(3);
  });

  it("同じ seq は新しい方で置き換える", () => {
    const old = phase(1, 0);
    const updated = phase(1, 2);
    expect(mergeEvents([old], [updated])).toEqual([updated]);
  });
});

describe("isTerminal", () => {
  it("判決と中断だけが終端", () => {
    expect(isTerminal({ type: "session_aborted", seq: 1, session_id: "s", reason: "x" })).toBe(true);
    expect(isTerminal(phase(1))).toBe(false);
  });
});

describe("llmCalls / foundEvidence", () => {
  it("LLM 呼び出しの記録だけを取り出す", () => {
    const call = {
      call_id: "c",
      started_at: "2026-01-01T00:00:00Z",
      role: "debater",
      model_key: "fast",
      model: "m",
      provider: "local",
      kind: "text" as const,
      total_ms: 10,
      success: true,
      attempts: 1,
      retries: 0,
    };
    const events: DebateEvent[] = [
      phase(1),
      { type: "llm_call_recorded", seq: 2, session_id: "s", call },
    ];
    expect(llmCalls(events)).toEqual([call]);
  });

  it("進捗メッセージから証拠品候補のタイトルを取り出す", () => {
    expect(foundEvidence(["検索中", "証拠品候補: 調査A", "証拠品化 1/3", "証拠品候補: 調査B"])).toEqual([
      "調査A",
      "調査B",
    ]);
  });
});
