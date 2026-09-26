import type { DebatePhase, Side } from "@/api/client";

export type TurnKey = { phase: DebatePhase; round: number; side: Side };

/** ストリーミング中の発言(SSE の turn / token から組み立てる表示用の状態)。 */
export type StreamingStatement = TurnKey & { text: string };

export function turnId(turn: TurnKey): string {
  return `${turn.phase}-${turn.round}-${turn.side}`;
}

export function startTurn(turn: TurnKey): StreamingStatement {
  return { ...turn, text: "" };
}

/** トークンを足す。別の手番のトークンなら新しい発言として始める。 */
export function appendToken(
  current: StreamingStatement | null,
  token: TurnKey & { text: string },
): StreamingStatement {
  if (current && turnId(current) === turnId(token)) {
    return { ...current, text: current.text + token.text };
  }
  return { phase: token.phase, round: token.round, side: token.side, text: token.text };
}
