/**
 * 立ち絵などの素材のパス。すべてオリジナルの仮素材で、差し替えはこのファイルだけで行う。
 */
export const ASSETS = {
  judge: "/assets/judge.svg",
  affirmative: "/assets/affirmative.svg",
  negative: "/assets/negative.svg",
  witness: "/assets/witness.svg",
  // 裁判型の開廷の場面の原告側(プレイヤー)・被告側。仮素材はディベートの立ち絵を流用する
  plaintiff: "/assets/affirmative.svg",
  defendant: "/assets/negative.svg",
} as const;

export const SPEAKER_NAMES = {
  judge: "裁判長",
  affirmative: "肯定側",
  negative: "否定側",
  plaintiff: "原告側",
  defendant: "被告側",
} as const;
