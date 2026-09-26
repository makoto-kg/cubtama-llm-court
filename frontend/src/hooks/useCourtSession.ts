"use client";

import { useCallback, useEffect, useRef } from "react";

import { api, ApiError, type DebateEvent, streamUrl, type SessionView, unwrap } from "@/api/client";
import { cutInForChoice, cutInForTurn } from "@/lib/cutin";
import { isTerminal, lastSeq } from "@/lib/events";
import type { TurnKey } from "@/lib/stream";
import { useCourtStore } from "@/store/court";

const REFRESH_DELAY_MS = 150;

function isFinished(view: SessionView | null): boolean {
  return view?.status === "finished" || view?.status === "aborted";
}

/**
 * セッションの状態の取得と SSE の購読をまとめる。
 *
 * - `debate`(永続イベント)や `task` を受けたら `GET /sessions/{id}` で表示を取り直す
 * - `turn` / `token` はストリーミング中の発言としてそのまま流す
 * - 判決・中断のイベントで接続を閉じる(EventSource の自動再接続を止める)
 */
export function useCourtSession(sessionId: string | null) {
  const store = useCourtStore;
  const refreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const refresh = useCallback(async () => {
    if (!sessionId) return;
    try {
      const view = unwrap(
        await api.GET("/api/sessions/{session_id}", { params: { path: { session_id: sessionId } } }),
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
    const state = store.getState();
    state.reset(sessionId);
    let source: EventSource | null = null;
    let closed = false;

    const open = (after: number) => {
      source = new EventSource(streamUrl(sessionId, after));
      source.addEventListener("debate", (message) => {
        const event = JSON.parse((message as MessageEvent<string>).data) as DebateEvent;
        const s = store.getState();
        s.addEvents([event]);
        if (event.type === "statement_made") s.endStreaming();
        if (event.type === "choice_made") {
          const text = cutInForChoice(event.option);
          if (text) s.showCutIn(text);
        }
        scheduleRefresh();
        if (isTerminal(event)) {
          closed = true;
          source?.close();
        }
      });
      source.addEventListener("turn", (message) => {
        const turn = JSON.parse((message as MessageEvent<string>).data) as TurnKey;
        const s = store.getState();
        s.startTurn(turn);
        const text = cutInForTurn(turn, s.view?.human_side);
        if (text) s.showCutIn(text);
      });
      source.addEventListener("token", (message) => {
        store.getState().appendToken(JSON.parse((message as MessageEvent<string>).data));
      });
      source.addEventListener("progress", (message) => {
        const data = JSON.parse((message as MessageEvent<string>).data) as { message: string };
        store.getState().pushProgress(data.message);
      });
      source.addEventListener("task", (message) => {
        const task = JSON.parse((message as MessageEvent<string>).data);
        store.getState().setTask(task);
        if (task.status !== "started") scheduleRefresh();
      });
      source.onerror = () => {
        // 閉廷後にサーバーが接続を閉じた場合は再接続しない(それ以外は EventSource が再接続する)
        if (closed || isFinished(store.getState().view)) source?.close();
      };
    };

    void (async () => {
      try {
        const [view, events] = await Promise.all([
          api.GET("/api/sessions/{session_id}", { params: { path: { session_id: sessionId } } }),
          api.GET("/api/sessions/{session_id}/events", {
            params: { path: { session_id: sessionId }, query: { after: 0 } },
          }),
        ]);
        const loaded = unwrap(events);
        const s = store.getState();
        s.setView(unwrap(view));
        s.addEvents(loaded);
        if (!isFinished(s.view) && !closed) open(lastSeq(loaded));
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
    advance: () => call(async () => unwrap(await api.POST("/api/sessions/{session_id}/advance", path))),
    run: () => call(async () => unwrap(await api.POST("/api/sessions/{session_id}/run", path))),
    research: () =>
      call(async () => unwrap(await api.POST("/api/sessions/{session_id}/research", path))),
    choose: (optionId: string) =>
      call(async () =>
        unwrap(
          await api.POST("/api/sessions/{session_id}/choices", {
            ...path,
            body: { option_id: optionId },
          }),
        ),
      ),
  };
}
