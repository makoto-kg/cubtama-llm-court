import type { DebateEvent, LLMCallInfo } from "@/api/client";

/** seq で重複を除いて並べる。同じ seq は新しい方(秘匿が解けた版など)で置き換える。 */
export function mergeEvents(existing: DebateEvent[], incoming: DebateEvent[]): DebateEvent[] {
  const bySeq = new Map<number, DebateEvent>();
  for (const event of existing) bySeq.set(event.seq ?? 0, event);
  for (const event of incoming) bySeq.set(event.seq ?? 0, event);
  return [...bySeq.values()].sort((a, b) => (a.seq ?? 0) - (b.seq ?? 0));
}

export function lastSeq(events: DebateEvent[]): number {
  return events.reduce((max, e) => Math.max(max, e.seq ?? 0), 0);
}

export function isTerminal(event: DebateEvent): boolean {
  return (
    event.type === "verdict_delivered" ||
    event.type === "session_aborted" ||
    event.type === "trial_finished"
  );
}

export function llmCalls(events: DebateEvent[]): LLMCallInfo[] {
  const calls: LLMCallInfo[] = [];
  for (const event of events) {
    if (event.type === "llm_call_recorded") calls.push(event.call);
  }
  return calls;
}

export const FOUND_PREFIX = "証拠品候補: ";

/** 捜査の進捗メッセージから、見つかった証拠品候補のタイトルを取り出す。 */
export function foundEvidence(progress: string[]): string[] {
  return progress.filter((m) => m.startsWith(FOUND_PREFIX)).map((m) => m.slice(FOUND_PREFIX.length));
}
