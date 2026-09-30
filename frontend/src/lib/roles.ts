import type { TrialView } from "@/api/client";
import { JUDGE_NAME } from "@/assets/manifest";

import { defendantOf } from "./opening";
import { personName } from "./trial";

/**
 * 名札に出す名前(台詞の中の名前は変えない)。
 * 被告は「名前（被告）」、検察官は「名前（検察官）」にする。
 */
export function speakerLabel(view: TrialView, personId: string): string {
  const name = personName(view, personId);
  return defendantOf(view)?.id === personId ? `${name}（被告）` : name;
}

/** 検察官(プレイヤー)の名札。演じる人物が決まっていれば「名前（検察官）」、なければ「検察官（あなた）」。 */
export function prosecutorLabel(view: TrialView): string {
  const id = view.case.prosecutor_id;
  const person = id ? view.case.people.find((p) => p.id === id) : undefined;
  return person ? `${person.name}（検察官）` : "検察官（あなた）";
}

/** 裁判官の名札(「アヤ（裁判官）」)。 */
export function judgeLabel(): string {
  return `${JUDGE_NAME}（裁判官）`;
}

/** 被告の名札(被告が決まっていない旧形式の事件は「被告」)。 */
export function defendantLabel(view: TrialView): string {
  const defendant = defendantOf(view);
  return defendant ? `${defendant.name}（被告）` : "被告";
}
