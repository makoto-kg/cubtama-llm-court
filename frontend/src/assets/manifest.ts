import { withBasePath } from "@/lib/basePath";

/**
 * 立ち絵などの素材のパス。すべてオリジナルの素材で、差し替えはこのファイルだけで行う。
 * 裁判型の 3 人の立ち絵は `public/assets/characters/` の透過 PNG(`scripts/cutout_sprites.py` で元画像から作る)。
 */
export const ASSETS = {
  judge: withBasePath("/assets/characters/aya_standard.png"),
  affirmative: withBasePath("/assets/affirmative.svg"),
  negative: withBasePath("/assets/negative.svg"),
} as const;

/** 立ち絵の表情・ポーズ。 */
export type CharacterPose = "standard" | "nervous" | "lose" | "igiari";

export type Sprite = { src: string; width: number; height: number };

function sprite(name: string, width: number, height: number): Sprite {
  return { src: withBasePath(`/assets/characters/${name}.png`), width, height };
}

/**
 * 裁判型の法廷に立つ 3 人の立ち絵(ADR 0017)。どの事件でも同じ顔ぶれが演じる。
 * - 裁判官: アヤ裁判長
 * - 検察官(プレイヤー): タマ。`igiari` は証拠品をつきつけるとき、`lose` はゲージが尽きて審理が中断したとき
 * - 被告: カブ。`nervous` は矛盾を突かれたとき、`lose` は有罪の判決を受けたとき
 */
export const TRIAL_SPRITES: {
  judge: { standard: Sprite };
  prosecutor: { standard: Sprite; igiari: Sprite; lose: Sprite };
  defendant: { standard: Sprite; nervous: Sprite; lose: Sprite };
} = {
  judge: { standard: sprite("aya_standard", 795, 1100) },
  prosecutor: {
    standard: sprite("tama_standard", 784, 1100),
    igiari: sprite("tama_igiari", 1100, 858),
    lose: sprite("tama_lose", 790, 1100),
  },
  defendant: {
    standard: sprite("cub_standard", 751, 1100),
    nervous: sprite("cub_nervous", 801, 1100),
    lose: sprite("cub_lose", 828, 1100),
  },
};

/** 役と表情から立ち絵を選ぶ。その役にない表情は通常の立ち絵にする。 */
export function trialSprite(role: keyof typeof TRIAL_SPRITES, pose: CharacterPose = "standard"): Sprite {
  const poses: Partial<Record<CharacterPose, Sprite>> & { standard: Sprite } = TRIAL_SPRITES[role];
  return poses[pose] ?? poses.standard;
}

/** タイトルロゴ(`scripts/cutout_sprites.py` で元画像から背景を抜いた透過 PNG)。 */
export const TITLE_LOGO: Sprite = { src: withBasePath("/assets/title.png"), width: 1600, height: 879 };

/** タイトル(ロゴの画像の代替テキストにも使う)とサブタイトル。 */
export const GAME_TITLE = "にゃくてん裁判";
export const GAME_SUBTITLE = "そのトークンに異議あり";

export const SPEAKER_NAMES = {
  judge: "裁判長",
  affirmative: "肯定側",
  negative: "否定側",
} as const;

/** 裁判型の裁判官の名前(どの事件でも同じ人物。立ち絵は `TRIAL_SPRITES.judge`)。 */
export const JUDGE_NAME = "アヤ";

/** 裁判型の法廷に立つ 3 人(ADR 0017)。検察官はプレイヤー。 */
export const TRIAL_ROLE_NAMES = {
  judge: "裁判官",
  prosecutor: "検察官",
  defendant: "被告",
} as const;
