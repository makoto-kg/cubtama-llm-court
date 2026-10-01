import { withBasePath } from "@/lib/basePath";

/** オフラインパックの場所(静的ファイルとして同梱する)。 */
export const OFFLINE_BASE = withBasePath("/offline");

export function packUrl(caseId: string): string {
  return `${OFFLINE_BASE}/cases/${encodeURIComponent(caseId)}.json`;
}

export const INDEX_URL = `${OFFLINE_BASE}/index.json`;
