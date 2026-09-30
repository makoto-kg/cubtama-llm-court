import type { DebatePhase, Side } from "@/api/client";

export const SIDE_LABELS: Record<Side, string> = {
  affirmative: "肯定側",
  negative: "否定側",
};

export const PHASE_LABELS: Record<DebatePhase, string> = {
  opening: "冒頭陳述",
  rebuttal: "反論",
  closing: "最終弁論",
  verdict: "判決",
};

export const CHOICE_KIND_LABELS: Record<string, string> = {
  contradiction: "つきつける",
  probe: "ゆさぶる",
  argument: "方針",
};

export const STRENGTH_LABELS: Record<string, string> = {
  strong: "有効",
  weak: "弱い",
  trap: "罠",
};

export const ROLE_LABELS: Record<string, string> = {
  researcher: "捜査官",
  debater: "論者",
  claim_extractor: "書記官",
  analyst: "分析官",
  advocate: "代弁者",
  judge: "裁判長",
  scenario_writer: "脚本家",
  witness: "被告役",
  solver: "解答者",
};

export const RUBRIC_LABELS: Record<string, string> = {
  logic: "論理の一貫性",
  evidence: "証拠の使い方",
  rebuttal: "反論の的確さ",
  persuasiveness: "説得力",
};

export const ISSUE_LABELS: Record<string, string> = {
  unknown_evidence: "存在しない証拠品",
  unsupported_quote: "証拠品にない引用",
  no_citation: "出典なし",
};

export function phaseTitle(phase: DebatePhase, round: number): string {
  return PHASE_LABELS[phase] + (round ? ` 第${round}回` : "");
}
