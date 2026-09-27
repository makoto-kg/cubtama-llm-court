import type {
  ExplanationObjected,
  ObjectionTarget,
  OfflinePack,
  OfflineResponse,
  TrialExchange,
  TrialOption,
  TrialView,
} from "@/api/client";

import { prepareOptions, triedKey } from "./analyst";

/**
 * オフラインの裁判の進行(backend の `TrialEngine` / `TrialState` の移植)。
 *
 * 状態の真実は「選んだ行動の列」で、状態は `replay` で毎回作り直す(イベントログの考え方)。
 * 証人の応答は、事前シミュレーションでパックに入れたものを行動キーで引く。
 */

export type OfflineAction =
  | { kind: "choose"; optionId: string }
  | { kind: "answer"; index: number }
  | { kind: "object"; targetKind: ObjectionTarget; targetId: string; comment: string; at: string };

export type OfflineState = {
  pack: OfflinePack;
  seed: string;
  gauge: number;
  testimonyId: string | null;
  pending: TrialOption[];
  exchanges: TrialExchange[];
  calls: NonNullable<OfflineResponse["call"]>[];
  tried: Set<string>;
  solved: string[];
  prepared: number;
  answerIndex: number | null;
  answerCorrect: boolean | null;
  result: TrialView["result"];
  objections: ExplanationObjected[];
};

export class OfflineActionError extends Error {}

export function presentKey(lineId: string, evidenceId: string): string {
  return `present:${lineId}:${evidenceId}`;
}

export function probeKey(lineId: string): string {
  return `probe:${lineId}`;
}

export function responseKey(option: TrialOption): string {
  return option.kind === "present" && option.evidence_id
    ? presentKey(option.line_id, option.evidence_id)
    : probeKey(option.line_id);
}

function unsolvedIn(state: OfflineState, testimonyId: string): boolean {
  const testimony = state.pack.case.testimonies.find((t) => t.id === testimonyId);
  if (!testimony) return false;
  const lineIds = new Set(testimony.lines.map((l) => l.id));
  return state.pack.answers.contradictions.some(
    (c) => lineIds.has(c.testimony_line_id) && !state.solved.includes(c.id),
  );
}

function allSolved(state: OfflineState): boolean {
  return state.solved.length === state.pack.answers.contradictions.length;
}

/** 次の証言に入り、選択肢を用意する(全矛盾を解いていれば何もしない)。 */
function next(state: OfflineState): OfflineState {
  if (state.result !== null || allSolved(state)) return { ...state, pending: [] };
  let testimonyId = state.testimonyId;
  if (testimonyId === null || !unsolvedIn(state, testimonyId)) {
    testimonyId = state.pack.case.testimonies.find((t) => unsolvedIn(state, t.id))?.id ?? null;
  }
  const testimony = state.pack.case.testimonies.find((t) => t.id === testimonyId);
  if (!testimony) return { ...state, pending: [] };
  const number = state.exchanges.length + 1;
  const pending = prepareOptions({
    pack: state.pack,
    testimony,
    solved: new Set(state.solved),
    tried: state.tried,
    idPrefix: `Q${String(number).padStart(2, "0")}`,
    seed: `${state.seed}-${number}`,
  });
  return { ...state, testimonyId: testimony.id, pending, prepared: state.prepared + 1 };
}

export function start(pack: OfflinePack, seed: string): OfflineState {
  return next({
    pack,
    seed,
    gauge: pack.mode.penalty_gauge,
    testimonyId: null,
    pending: [],
    exchanges: [],
    calls: [],
    tried: new Set(),
    solved: [],
    prepared: 0,
    answerIndex: null,
    answerCorrect: null,
    result: null,
    objections: [],
  });
}

function choose(state: OfflineState, optionId: string): OfflineState {
  if (state.result !== null || state.pending.length === 0) {
    throw new OfflineActionError("選択を受け付ける場面ではありません");
  }
  const option = state.pending.find((o) => o.id === optionId);
  if (!option) throw new OfflineActionError(`選択肢 ${optionId} はありません`);
  const testimony = state.pack.case.testimonies.find((t) => t.id === state.testimonyId)!;
  const response = state.pack.responses.find((r) => r.key === responseKey(option));
  const penalty = state.pack.mode.penalties[option.strength ?? ""] ?? 0;
  const solved = option.contradiction_id ? [...state.solved, option.contradiction_id] : state.solved;
  const gauge = state.gauge - penalty;
  const exchange: TrialExchange = {
    option,
    witness_id: response?.witness_id ?? testimony.witness_id,
    text: response?.text ?? "……。",
    solved: option.contradiction_id != null,
    penalty,
    check: response?.check ?? null,
  };
  const updated: OfflineState = {
    ...state,
    gauge,
    pending: [],
    exchanges: [...state.exchanges, exchange],
    calls: response?.call ? [...state.calls, response.call] : state.calls,
    tried: new Set([...state.tried, triedKey(option)]),
    solved,
    result: gauge <= 0 ? "penalty" : null,
  };
  return next(updated);
}

function answer(state: OfflineState, index: number): OfflineState {
  if (state.result !== null || !allSolved(state)) {
    throw new OfflineActionError("最後の問いに答える場面ではありません");
  }
  if (index < 0 || index >= state.pack.case.question.options.length) {
    throw new OfflineActionError(`選択肢 ${index} はありません`);
  }
  const correct = index === state.pack.answers.answer_index;
  return {
    ...state,
    answerIndex: index,
    answerCorrect: correct,
    result: correct ? "solved" : "wrong_answer",
  };
}

function object(state: OfflineState, action: Extract<OfflineAction, { kind: "object" }>): OfflineState {
  if (state.result === null) throw new OfflineActionError("解説への異議は閉廷後に送れます");
  if (!action.comment.trim()) throw new OfflineActionError("コメントが空です");
  const objection: ExplanationObjected = {
    type: "explanation_objected",
    session_id: state.seed,
    seq: state.objections.length + 1,
    timestamp: action.at,
    target_kind: action.targetKind,
    target_id: action.targetId,
    comment: action.comment.trim(),
  };
  return { ...state, objections: [...state.objections, objection] };
}

export function apply(state: OfflineState, action: OfflineAction): OfflineState {
  switch (action.kind) {
    case "choose":
      return choose(state, action.optionId);
    case "answer":
      return answer(state, action.index);
    case "object":
      return object(state, action);
  }
}

/** 行動の列から状態を作り直す。 */
export function replay(pack: OfflinePack, seed: string, actions: readonly OfflineAction[]): OfflineState {
  return actions.reduce(apply, start(pack, seed));
}

/** 表示用に、オンラインの `TrialView` と同じ形にする(正解は伏せる)。 */
export function toTrialView(state: OfflineState): TrialView {
  const { pack } = state;
  const finished = state.result !== null;
  const contradictions = new Map(pack.answers.contradictions.map((c) => [c.id, c]));
  const stage: TrialView["stage"] = finished ? "finished" : allSolved(state) ? "answering" : "choosing";
  return {
    session_id: state.seed,
    case: pack.case,
    status: finished ? "finished" : stage === "answering" ? "answering" : "in_progress",
    stage,
    running_task: null,
    models: pack.meta.models,
    testimony_id: state.testimonyId,
    pending_options: state.pending.map((o) => ({ ...o, strength: null, contradiction_id: null, trap_reason: null })),
    exchanges: state.exchanges.map((x) => ({ ...x, check: finished ? x.check : null })),
    solved_line_ids: state.solved.map((id) => contradictions.get(id)?.testimony_line_id ?? id),
    solved_count: state.solved.length,
    contradiction_count: pack.answers.contradictions.length,
    penalty_gauge: state.gauge,
    penalty_gauge_max: pack.mode.penalty_gauge,
    answer_index: state.answerIndex,
    answer_correct: state.answerCorrect,
    result: state.result,
    aborted: null,
    explanation: finished ? pack.explanation : null,
    objections: state.objections,
  };
}
