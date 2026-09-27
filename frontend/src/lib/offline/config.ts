/** `NEXT_PUBLIC_OFFLINE_ONLY=1` でビルドすると、API を使う画面への導線を出さない(配布用)。 */
export const OFFLINE_ONLY = process.env.NEXT_PUBLIC_OFFLINE_ONLY === "1";

/** オフラインパックの場所(静的ファイルとして同梱する)。 */
export const OFFLINE_BASE = "/offline";

export function packUrl(caseId: string): string {
  return `${OFFLINE_BASE}/cases/${encodeURIComponent(caseId)}.json`;
}

export const INDEX_URL = `${OFFLINE_BASE}/index.json`;
