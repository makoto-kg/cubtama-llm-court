import type { DebateEvent, Explanation, ObjectionTarget, TrialOption, TrialView } from "@/api/client";

import { CUT_IN_TEXT } from "./cutin";

/** ストリーミング中の証人の応答(SSE の witness / token から組み立てる)。 */
export type WitnessStream = { witnessId: string; text: string };

export function appendWitnessToken(
  current: WitnessStream | null,
  token: { witness_id: string; text: string },
): WitnessStream {
  if (current && current.witnessId === token.witness_id) {
    return { ...current, text: current.text + token.text };
  }
  return { witnessId: token.witness_id, text: token.text };
}

/** 選択の直後に出すカットイン。つきつける = 反証、ゆさぶる = 確認。 */
export function cutInForTrialChoice(option: TrialOption): string {
  return option.kind === "present" ? CUT_IN_TEXT.contradiction : CUT_IN_TEXT.probe;
}

/** 証言が崩れた瞬間の、強い演出のカットイン。 */
export const COLLAPSE_CUT_IN = "証言崩壊!";

/**
 * 永続イベントから出すカットイン(選んだ瞬間の「反証!」「確認!」)。
 * 「証言崩壊!」はここでは出さない。被告の応答を読み終えてから画面が出す(`pendingCollapse`)。
 */
export function cutInForTrialEvent(event: DebateEvent): string | null {
  if (event.type === "trial_choice_made") return cutInForTrialChoice(event.option);
  return null;
}

/**
 * まだ「証言崩壊!」を見せていない、証言が崩れた応答の番号。
 * 最新の応答が崩れた応答で、`shownUpTo`(見せ終えた応答の番号)より後なら、その番号を返す。
 */
export function pendingCollapse(exchanges: readonly { solved: boolean }[], shownUpTo: number): number | null {
  const i = exchanges.length - 1;
  return i >= 0 && i > shownUpTo && exchanges[i].solved ? i : null;
}

function quoteLine(text: string, limit = 28): string {
  return text.length <= limit ? text : `${text.slice(0, limit - 1)}…`;
}

/** 検察官の台詞(定型文)の口調。事件の `prosecutor_speech`。cat は猫言葉。 */
export type ProsecutorSpeech = "plain" | "cat";

const PROBE_LINES: Record<ProsecutorSpeech, ((line: string) => string)[]> = {
  plain: [
    (line) => `今の証言、「${line}」……もう少し詳しく聞かせてもらいましょう。`,
    (line) => `「${line}」とおっしゃいましたね。具体的に説明してください。`,
    (line) => `その話、どうも引っかかります。「${line}」とは、どういう意味ですか?`,
  ],
  cat: [
    (line) => `今の証言、「${line}」……もうちょっと詳しく聞かせてもらうにゃ。`,
    (line) => `「${line}」って言ったにゃ? くわしく説明するにゃ!`,
    (line) => `その話、なんだかくさいにゃ……。「${line}」って、どういうことにゃ?`,
  ],
};

const PRESENT_LINES: Record<ProsecutorSpeech, ((line: string, evidence: string) => string)[]> = {
  plain: [
    (line, evidence) => `「${line}」……本当ですか? では、この「${evidence}」をご覧ください!`,
    (_line, evidence) => `今の証言は、この「${evidence}」と食い違っています!`,
    (line, evidence) => `「${evidence}」を見てください。これでもまだ「${line}」と言い張りますか?`,
  ],
  cat: [
    (line, evidence) => `「${line}」……ほんとかにゃ? じゃあ、この「${evidence}」を見るにゃ!`,
    (_line, evidence) => `今の証言は、この「${evidence}」と食いちがってるにゃ!`,
    (line, evidence) => `「${evidence}」を見るにゃ。これでもまだ「${line}」って言いはるのかにゃ?`,
  ],
};

/**
 * 「ゆさぶる」「つきつける」を選んだときの検察官(プレイヤー)の台詞。オリジナルの定型文で、LLM は使わない。
 * 手番の番号 `n` で言い回しを変える(同じ手番なら同じ台詞)。口調は事件の `prosecutor_speech`。
 */
export function prosecutorLine(
  option: TrialOption,
  lineText: string,
  evidenceName: string | null,
  n: number,
  speech: ProsecutorSpeech = "plain",
): string {
  const line = quoteLine(lineText);
  // 口調の欄がない古いパックは、ふつうの口調にする
  if (option.kind === "probe") {
    const lines = PROBE_LINES[speech] ?? PROBE_LINES.plain;
    return lines[n % lines.length](line);
  }
  const lines = PRESENT_LINES[speech] ?? PRESENT_LINES.plain;
  return lines[n % lines.length](line, evidenceName ?? "この証拠品");
}

export function isTrialFinished(view: TrialView | null): boolean {
  return view?.status === "finished" || view?.status === "aborted";
}

export const RESULT_LABELS: Record<string, string> = {
  solved: "事件解決",
  wrong_answer: "問いの答えが違いました",
  penalty: "ペナルティゲージが尽きました",
};

/** 現在の証言(公開の事件から)。 */
export function currentTestimony(view: TrialView) {
  return view.case.testimonies.find((t) => t.id === view.testimony_id) ?? null;
}

/** 証言の読み上げの前後に出すカットイン(オリジナルの文言)。 */
export const TESTIMONY_CUT_IN = { start: "証言開始", examine: "尋問開始" } as const;

/** 現在の証言の尋問がもう始まっているか(その証言の行への行動がある)。始まっていれば読み上げを省く。 */
export function testimonyExamined(view: TrialView): boolean {
  const testimony = currentTestimony(view);
  if (!testimony) return false;
  const lineIds = new Set(testimony.lines.map((l) => l.id));
  return view.exchanges.some((x) => lineIds.has(x.option.line_id));
}

export function personName(view: TrialView, personId: string): string {
  return view.case.people.find((p) => p.id === personId)?.name ?? personId;
}

/** 選択肢を行ごとにまとめる(証言の行の順)。 */
export function optionsByLine(
  lineIds: string[],
  options: TrialOption[],
): { lineId: string; options: TrialOption[] }[] {
  return lineIds
    .map((lineId) => ({ lineId, options: options.filter((o) => o.line_id === lineId) }))
    .filter((g) => g.options.length > 0);
}

/**
 * 尋問で最初に指す証言の行。前に指していた行が今の証言にあればそのまま、
 * なければ選択肢のある最初の行(なければ先頭)。
 */
export function focusLine(
  lineIds: string[],
  groups: { lineId: string }[],
  previous: string | null,
): string | null {
  if (previous && lineIds.includes(previous)) return previous;
  return groups[0]?.lineId ?? lineIds[0] ?? null;
}

/** 証言の行を前後に送る(端から端へ回る)。 */
export function stepLine(lineIds: string[], current: string | null, delta: number): string | null {
  if (lineIds.length === 0) return null;
  const i = current ? lineIds.indexOf(current) : -1;
  const base = i < 0 ? 0 : i;
  return lineIds[(base + delta + lineIds.length) % lineIds.length];
}

export type ObjectionTargetOption = { kind: ObjectionTarget; id: string; label: string };

/** 「解説に異議あり」で指せる項目。罠の ID は「矛盾の ID/証拠品の ID」。 */
export function objectionTargets(explanation: Explanation): ObjectionTargetOption[] {
  const targets: ObjectionTargetOption[] = [];
  for (const item of explanation.items) {
    targets.push({
      kind: "contradiction",
      id: item.contradiction_id,
      label: `矛盾: 「${item.testimony_line}」× ${item.evidence_name}`,
    });
    for (const trap of item.traps) {
      targets.push({
        kind: "trap",
        id: `${item.contradiction_id}/${trap.evidence_id}`,
        label: `罠: ${trap.evidence_name}(「${item.testimony_line}」)`,
      });
    }
  }
  for (const lp of explanation.learning_points) {
    targets.push({ kind: "learning_point", id: lp.id, label: `知識: ${lp.knowledge}` });
  }
  return targets;
}
