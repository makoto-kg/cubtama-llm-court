/**
 * 立ち絵などの素材のパス。すべてオリジナルの仮素材で、差し替えはこのファイルだけで行う。
 */
export const ASSETS = {
  judge: "/assets/judge.svg",
  affirmative: "/assets/affirmative.svg",
  negative: "/assets/negative.svg",
} as const;

export const SPEAKER_NAMES = {
  judge: "裁判長",
  affirmative: "肯定側",
  negative: "否定側",
} as const;
