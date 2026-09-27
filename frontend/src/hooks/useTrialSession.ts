"use client";

import { useCallback, useEffect, useRef } from "react";

import {
  api,
  ApiError,
  type DebateEvent,
  type ObjectionTarget,
  streamUrl,
  unwrap,
} from "@/api/client";
import { isTerminal, lastSeq } from "@/lib/events";
import { COLLAPSE_CUT_IN, cutInForTrialEvent, isTrialFinished } from "@/lib/trial";
import { useTrialStore } from "@/store/trial";

const REFRESH_DELAY_MS = 150;

/**
 * 裁判の状態の取得と SSE の購読をまとめる(`useCourtSession` の裁判版)。
 *
 * - `debate`(永続イベント)や `task` を受けたら `GET /trials/{id}` で表示を取り直す
 * - `witness` / `token` はストリーミング中の証人の応答としてそのまま流す
 * - 閉廷・中断のイベントで接続を閉じる
 */
export function useTrialSession(sessionId: string | null) {
  const store = useTrialStore;
  const refreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const refresh = useCallback(async () => {
    if (!sessionId) return;
    try {
      const view = unwrap(
        await api.GET("/api/trials/{session_id}", { params: { path: { session_id: sessionId } } }),
      );
      store.getState().setView(view);
    } catch (e) {
      store.getState().setError(e instanceof Error ? e.message : String(e));
    }
  }, [sessionId, store]);

  const scheduleRefresh = useCallback(() => {
    if (refreshTimer.current) clearTimeout(refreshTimer.current);
    refreshTimer.current = setTimeout(() => void refresh(), REFRESH_DELAY_MS);
  }, [refresh]);

  useEffect(() => {
    if (!sessionId) return;
    store.getState().reset(sessionId);
    let source: EventSource | null = null;
    let closed = false;

    const open = (after: number) => {
      source = new EventSource(streamUrl(sessionId, after));
      source.addEventListener("debate", (message) => {
        const event = JSON.parse((message as MessageEvent<string>).data) as DebateEvent;
        const s = store.getState();
        s.addEvents([event]);
        if (event.type === "witness_responded") s.endStreaming();
        const cutIn = cutInForTrialEvent(event);
        if (cutIn) s.showCutIn(cutIn, cutIn === COLLAPSE_CUT_IN);
        scheduleRefresh();
        if (isTerminal(event)) {
          closed = true;
          source?.close();
        }
      });
      source.addEventListener("witness", (message) => {
        const data = JSON.parse((message as MessageEvent<string>).data) as { witness_id: string };
        store.getState().startWitness(data.witness_id);
      });
      source.addEventListener("token", (message) => {
        store.getState().appendToken(JSON.parse((message as MessageEvent<string>).data));
      });
      source.addEventListener("progress", (message) => {
        const data = JSON.parse((message as MessageEvent<string>).data) as { message: string };
        store.getState().setProgress(data.message);
      });
      source.addEventListener("task", (message) => {
        const task = JSON.parse((message as MessageEvent<string>).data);
        const s = store.getState();
        s.setTask(task);
        if (task.status !== "started") {
          s.setProgress(null);
          scheduleRefresh();
        }
      });
      source.onerror = () => {
        if (closed || isTrialFinished(store.getState().view)) source?.close();
      };
    };

    void (async () => {
      try {
        const [view, events] = await Promise.all([
          api.GET("/api/trials/{session_id}", { params: { path: { session_id: sessionId } } }),
          api.GET("/api/sessions/{session_id}/events", {
            params: { path: { session_id: sessionId }, query: { after: 0 } },
          }),
        ]);
        const loaded = unwrap(events);
        const s = store.getState();
        s.setView(unwrap(view));
        s.addEvents(loaded);
        if (!isTrialFinished(s.view) && !closed) open(lastSeq(loaded));
      } catch (e) {
        store.getState().setError(e instanceof ApiError ? e.message : String(e));
      }
    })();

    return () => {
      closed = true;
      source?.close();
      if (refreshTimer.current) clearTimeout(refreshTimer.current);
    };
  }, [sessionId, store, scheduleRefresh]);

  /** 閉廷後はイベントの秘匿が解けるので、ログを取り直す。 */
  const reloadEvents = useCallback(async () => {
    if (!sessionId) return;
    const events = unwrap(
      await api.GET("/api/sessions/{session_id}/events", {
        params: { path: { session_id: sessionId }, query: { after: 0 } },
      }),
    );
    store.getState().addEvents(events);
  }, [sessionId, store]);

  const call = useCallback(
    async (action: () => Promise<unknown>) => {
      store.getState().setError(null);
      try {
        await action();
      } catch (e) {
        store.getState().setError(e instanceof Error ? e.message : String(e));
      }
      scheduleRefresh();
    },
    [store, scheduleRefresh],
  );

  const path = { params: { path: { session_id: sessionId ?? "" } } };
  return {
    refresh,
    reloadEvents,
    advance: () => call(async () => unwrap(await api.POST("/api/trials/{session_id}/advance", path))),
    choose: (optionId: string) =>
      call(async () =>
        unwrap(await api.POST("/api/trials/{session_id}/choices", { ...path, body: { option_id: optionId } })),
      ),
    answer: (index: number) =>
      call(async () => {
        const view = unwrap(await api.POST("/api/trials/{session_id}/answer", { ...path, body: { index } }));
        store.getState().setView(view);
        await reloadEvents();
      }),
    object: (targetKind: ObjectionTarget, targetId: string, comment: string) =>
      call(async () => {
        const view = unwrap(
          await api.POST("/api/trials/{session_id}/objections", {
            ...path,
            body: { target_kind: targetKind, target_id: targetId, comment },
          }),
        );
        store.getState().setView(view);
      }),
  };
}
