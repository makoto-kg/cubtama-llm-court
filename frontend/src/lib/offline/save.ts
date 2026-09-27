import type { OfflineAction } from "./engine";

/** オフラインの裁判の保存データ(真実は行動の列。状態は再生して作る)。 */
export type OfflineSave = { seed: string; actions: OfflineAction[] };

const PREFIX = "llm-court:offline:";

export function saveKey(caseId: string): string {
  return PREFIX + caseId;
}

export function parseSave(raw: string | null): OfflineSave | null {
  if (!raw) return null;
  try {
    const data = JSON.parse(raw) as Partial<OfflineSave>;
    if (typeof data.seed !== "string" || !Array.isArray(data.actions)) return null;
    return { seed: data.seed, actions: data.actions };
  } catch {
    return null;
  }
}

export function loadSave(caseId: string): OfflineSave | null {
  if (typeof localStorage === "undefined") return null;
  return parseSave(localStorage.getItem(saveKey(caseId)));
}

export function writeSave(caseId: string, save: OfflineSave): void {
  localStorage.setItem(saveKey(caseId), JSON.stringify(save));
}

export function clearSave(caseId: string): void {
  localStorage.removeItem(saveKey(caseId));
}

/** 文字を少しずつ出す区切り(証人の応答が「流れる」演出)。 */
export function revealSteps(text: string, chunk = 4): string[] {
  const steps: string[] = [];
  for (let i = chunk; i < text.length; i += chunk) steps.push(text.slice(0, i));
  steps.push(text);
  return steps;
}
