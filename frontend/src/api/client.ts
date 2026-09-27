import createClient from "openapi-fetch";

import type { components, paths } from "./schema";

/** バックエンドのオリジン。API は `${API_ORIGIN}/api/...`。 */
export const API_ORIGIN = (process.env.NEXT_PUBLIC_API_ORIGIN ?? "http://127.0.0.1:8000").replace(
  /\/$/,
  "",
);

export const api = createClient<paths>({ baseUrl: API_ORIGIN });

export function streamUrl(sessionId: string, after: number): string {
  return `${API_ORIGIN}/api/sessions/${encodeURIComponent(sessionId)}/stream?after=${after}`;
}

// --- 生成した型の別名(手書きの型は定義しない) ---

export type Schemas = components["schemas"];
export type SessionView = Schemas["SessionView"];
export type DebateEvent =
  paths["/api/sessions/{session_id}/events"]["get"]["responses"][200]["content"]["application/json"][number];
export type LLMCallInfo = Schemas["LLMCallInfo"];
export type ChoiceOption = Schemas["ChoiceOption"];
export type Evidence = Schemas["Evidence"];
export type Statement = Schemas["Statement"];
export type Side = Schemas["Statement"]["side"];
export type DebatePhase = Schemas["Statement"]["phase"];
export type TaskView = Schemas["TaskView"];
export type NextTurn = Schemas["NextTurn"];
export type CaseSummary = Schemas["CaseSummary"];
export type TrialView = Schemas["TrialView"];
export type TrialOption = Schemas["TrialOption"];
export type TrialExchange = Schemas["TrialExchange"];
export type Explanation = Schemas["Explanation"];
export type ObjectionTarget = Schemas["ObjectionRequest"]["target_kind"];
export type ExplanationObjected = Schemas["ExplanationObjected"];
export type OfflinePack = Schemas["OfflinePack"];
export type OfflineIndex = Schemas["OfflineIndex"];
export type OfflineResponse = Schemas["OfflineResponse"];

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

function detailOf(error: unknown): string {
  if (error && typeof error === "object" && "detail" in error) {
    const detail = (error as { detail: unknown }).detail;
    return typeof detail === "string" ? detail : JSON.stringify(detail);
  }
  return String(error ?? "不明なエラー");
}

/** openapi-fetch の結果から値を取り出す。失敗なら ApiError。 */
export function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (result.response.ok && result.data !== undefined) {
    return result.data;
  }
  throw new ApiError(result.response.status, detailOf(result.error));
}
