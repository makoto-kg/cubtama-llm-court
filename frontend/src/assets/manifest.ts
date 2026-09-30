/**
 * 立ち絵などの素材のパス。すべてオリジナルの仮素材で、差し替えはこのファイルだけで行う。
 */
export const ASSETS = {
  judge: "/assets/judge.svg",
  affirmative: "/assets/affirmative.svg",
  negative: "/assets/negative.svg",
  witness: "/assets/witness.svg",
  // 裁判型の検察官(プレイヤー)。仮素材はディベートの立ち絵を流用する。被告は証言台の立ち絵(witness)
  prosecutor: "/assets/affirmative.svg",
} as const;

export const SPEAKER_NAMES = {
  judge: "裁判長",
  affirmative: "肯定側",
  negative: "否定側",
} as const;

/** 裁判型の法廷に立つ 3 人(ADR 0017)。検察官はプレイヤー。 */
export const TRIAL_ROLE_NAMES = {
  judge: "裁判官",
  prosecutor: "検察官",
  defendant: "被告",
} as const;
