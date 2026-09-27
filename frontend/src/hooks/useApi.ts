"use client";

import { useEffect, useState } from "react";

import { api, type Schemas, type Side, unwrap } from "@/api/client";

type Loadable<T> = { data: T | null; error: string | null };

function message(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

function useLoad<T>(load: () => Promise<T>, deps: unknown[]): Loadable<T> {
  const [state, setState] = useState<Loadable<T>>({ data: null, error: null });
  useEffect(() => {
    let cancelled = false;
    load()
      .then((data) => !cancelled && setState({ data, error: null }))
      .catch((e: unknown) => !cancelled && setState({ data: null, error: message(e) }));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 呼び出し側が依存を渡す
  }, deps);
  return state;
}

/** タイトル画面: 同梱の捜査結果と最近のセッション。 */
export function useTitleData() {
  return useLoad(async () => {
    const [samples, sessions] = await Promise.all([
      api.GET("/api/evidence-samples").then(unwrap),
      api.GET("/api/sessions").then(unwrap),
    ]);
    return { samples, sessions: [...sessions].reverse().slice(0, 8) };
  }, []);
}

/** タイトル画面(裁判): 遊べる事件の一覧。 */
export function useCases(all: boolean) {
  return useLoad(() => api.GET("/api/cases", { params: { query: { all } } }).then(unwrap), [all]);
}

/** 事件を選んで開廷する。セッション ID を返す。 */
export async function openTrial(caseId: string): Promise<string> {
  return unwrap(await api.POST("/api/trials", { body: { case_id: caseId } })).session_id;
}

/** 設定画面: 役割ごとのモデル割り当て。 */
export function useConfig() {
  return useLoad(() => api.GET("/api/config").then(unwrap), []);
}

/** 判決画面: 法廷記録(Markdown)と計測サマリ。 */
export function useSessionReport(sessionId: string) {
  return useLoad(async () => {
    const path = { params: { path: { session_id: sessionId } } };
    const [record, summary] = await Promise.all([
      api.GET("/api/sessions/{session_id}/record", { ...path, parseAs: "text" }),
      api.GET("/api/sessions/{session_id}/summary", path).then(unwrap),
    ]);
    return { record: record.data ?? null, summary };
  }, [sessionId]);
}

export type EvidenceInput =
  | { source: "sample"; name: string }
  | { source: "upload"; file: File }
  | { source: "research" };

/** 開廷して証拠品をそろえる(捜査はバックグラウンドで始まる)。セッション ID を返す。 */
export async function openSession(
  topic: string,
  rounds: number,
  humanSide: Side | null,
  evidence: EvidenceInput,
): Promise<string> {
  const created = unwrap(await api.POST("/api/sessions", { body: { topic, rounds, human_side: humanSide } }));
  const sessionId = created.session_id;
  const path = { params: { path: { session_id: sessionId } } };
  if (evidence.source === "sample") {
    unwrap(
      await api.POST("/api/sessions/{session_id}/evidence/samples/{name}", {
        params: { path: { session_id: sessionId, name: evidence.name } },
      }),
    );
  } else if (evidence.source === "upload") {
    const report = JSON.parse(await evidence.file.text()) as Schemas["ResearchReport"];
    unwrap(await api.PUT("/api/sessions/{session_id}/evidence", { ...path, body: report }));
  } else {
    unwrap(await api.POST("/api/sessions/{session_id}/research", path));
  }
  return sessionId;
}
