/**
 * 遊び方のモード(ADR 0018)。ビルドは 1 本で、画面で選ぶ。既定はオフライン。
 * - offline: 同梱のパックで裁判を遊ぶ。API を呼ばない
 * - online: バックエンドにつなぐ(ディベート・オンラインの裁判・設定)
 */
export type AppMode = "offline" | "online";

export const DEFAULT_MODE: AppMode = "offline";

/** 選んだモードを覚えておく `localStorage` のキー(閲覧者ごとの設定)。 */
export const MODE_STORAGE_KEY = "llm-court:mode";

export const MODE_LABELS: Record<AppMode, string> = {
  offline: "オフライン",
  online: "オンライン",
};

/** 保存値をモードとして読む。未設定・不正な値は既定(オフライン)。 */
export function parseMode(value: string | null | undefined): AppMode {
  return value === "online" || value === "offline" ? value : DEFAULT_MODE;
}
