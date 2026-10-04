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

/**
 * 口パクに使う口の位置(立ち絵の画素の座標)。
 * - `x`・`y`: 口の合わせ目の中央
 * - `width`: 開いた口の幅
 * - `jaw`: 下あご(口の合わせ目からあご先まで)の高さ。この範囲を下げて口を開く
 * - `open`: 口を開いたときに下あごを下げる量
 */
export type Mouth = { x: number; y: number; width: number; jaw: number; open: number };

/**
 * 口を閉じた版の口まわり(口を開けて描いた立ち絵の口パクに使う)。立ち絵に重ねて出し入れする。
 * `x`・`y` は立ち絵の中の左上の位置(立ち絵の画素)。画像は `scripts/cutout_sprites.py` が位置と一緒に出力する。
 */
export type ClosedMouth = { src: string; x: number; y: number; width: number; height: number };

export type Sprite = { src: string; width: number; height: number; mouth?: Mouth; closedMouth?: ClosedMouth };

function sprite(name: string, width: number, height: number, mouth?: Mouth): Sprite {
  return { src: withBasePath(`/assets/characters/${name}.png`), width, height, mouth };
}

/** 口を開けて描いた立ち絵に、口を閉じた版の口まわり(`<name>_mouth.png`)を添える。 */
function withClosedMouth(base: Sprite, name: string, x: number, y: number, width: number, height: number): Sprite {
  return { ...base, closedMouth: { src: withBasePath(`/assets/characters/${name}_mouth.png`), x, y, width, height } };
}

/**
 * 裁判型の法廷に立つ 3 人の立ち絵(ADR 0017)。どの事件でも同じ顔ぶれが演じる。
 * - 裁判官: アヤ裁判長
 * - 検察官(プレイヤー): タマ。`igiari` は証拠品をつきつけるとき、`lose` はゲージが尽きて審理が中断したとき
 * - 被告: カブ。`nervous` は矛盾を突かれたとき、`lose` は有罪の判決を受けたとき
 *
 * 口の位置(`Mouth`)は話している間の口パクに使う。立ち絵を差し替えたら測り直す。
 * 口を開けて描いた立ち絵(`tama_igiari`)は下あごを動かさず、口を閉じた版の口まわり(`ClosedMouth`)を重ねて口パクする。
 */
export const TRIAL_SPRITES: {
  judge: { standard: Sprite };
  prosecutor: { standard: Sprite; igiari: Sprite; lose: Sprite };
  defendant: { standard: Sprite; nervous: Sprite; lose: Sprite };
} = {
  judge: { standard: sprite("aya_standard", 795, 1100, { x: 397, y: 325, width: 50, jaw: 48, open: 10 }) },
  prosecutor: {
    standard: sprite("tama_standard", 784, 1100, { x: 392, y: 270, width: 44, jaw: 44, open: 14 }),
    // 叫んで口を開けた絵なので、口を閉じた版の口まわりと入れ替えて口パクする
    igiari: withClosedMouth(sprite("tama_igiari", 1100, 858), "tama_igiari", 280, 149, 222, 178),
    lose: sprite("tama_lose", 790, 1100, { x: 550, y: 340, width: 26, jaw: 16, open: 7 }),
  },
  defendant: {
    standard: sprite("cub_standard", 751, 1100, { x: 375, y: 272, width: 44, jaw: 44, open: 14 }),
    nervous: sprite("cub_nervous", 801, 1100, { x: 440, y: 274, width: 44, jaw: 44, open: 14 }),
    lose: sprite("cub_lose", 828, 1100, { x: 610, y: 342, width: 26, jaw: 16, open: 7 }),
  },
};

/** 役と表情から立ち絵を選ぶ。その役にない表情は通常の立ち絵にする。 */
export function trialSprite(role: keyof typeof TRIAL_SPRITES, pose: CharacterPose = "standard"): Sprite {
  const poses: Partial<Record<CharacterPose, Sprite>> & { standard: Sprite } = TRIAL_SPRITES[role];
  return poses[pose] ?? poses.standard;
}

/**
 * BGM(どのページでも流す)。`.work/bgm.mp3` の前後の無音を削り、HE-AAC(32kbps・ステレオ)に縮めたもの(ADR 0023)。
 * 曲はそのままの長さで、くり返し流す。
 */
export const BGM = { src: withBasePath("/assets/audio/bgm.m4a"), volume: 0.35 } as const;

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
