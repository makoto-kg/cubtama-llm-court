import type { TrialOption } from "@/api/client";
import type { CharacterPose } from "@/assets/manifest";

type Choice = Pick<TrialOption, "kind"> & { strength?: TrialOption["strength"] };

/** 検察官(プレイヤー)の立ち絵: 証拠品をつきつけるときは決めのポーズ、ゆさぶるときは通常。 */
export function prosecutorPose(option: Choice | null): CharacterPose {
  return option?.kind === "present" ? "igiari" : "standard";
}

/**
 * 被告が応答するときの立ち絵: 証拠品をつきつけられたら困惑する。
 * ただし的外れな証拠品(`trap`)なら動じない。組の強さが分からない応答中(選ぶまで伏せている)は困惑させておく。
 */
export function defendantPose(option: Choice | null): CharacterPose {
  if (option?.kind !== "present") return "standard";
  return option.strength === "trap" ? "standard" : "nervous";
}
