"use client";

import { useEffect, useState } from "react";

import type { OfflineIndex, OfflinePack } from "@/api/client";
import { INDEX_URL, packUrl } from "@/lib/offline/config";
import { useOfflineStore } from "@/store/offline";

async function fetchJson<T>(url: string): Promise<T> {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url} を読み込めません(${response.status})`);
  return (await response.json()) as T;
}

/** 同梱しているオフラインの事件の一覧(API は使わない)。 */
export function useOfflineIndex() {
  const [state, setState] = useState<{ data: OfflineIndex | null; error: string | null }>({
    data: null,
    error: null,
  });
  useEffect(() => {
    let cancelled = false;
    fetchJson<OfflineIndex>(INDEX_URL)
      .then((data) => !cancelled && setState({ data, error: null }))
      .catch((e: unknown) => !cancelled && setState({ data: null, error: String(e instanceof Error ? e.message : e) }));
    return () => {
      cancelled = true;
    };
  }, []);
  return state;
}

/** オフラインパックを読み込み、保存データから再開する。 */
export function useOfflineTrial(caseId: string | null) {
  const load = useOfflineStore((s) => s.load);
  const setError = useOfflineStore((s) => s.setError);
  useEffect(() => {
    if (!caseId) return;
    let cancelled = false;
    fetchJson<OfflinePack>(packUrl(caseId))
      .then((pack) => !cancelled && load(caseId, pack))
      .catch((e: unknown) => !cancelled && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      cancelled = true;
    };
  }, [caseId, load, setError]);
}
