"use client";

import { useCallback, useSyncExternalStore } from "react";

import { type AppMode, DEFAULT_MODE, MODE_STORAGE_KEY, parseMode } from "@/lib/mode";

const CHANGE_EVENT = "llm-court:mode-change";

/** ストレージに保存できない環境(プライベートブラウズ等)でも、開いている間は選んだモードを保つ。 */
let chosen: AppMode | null = null;

function read(): AppMode {
  try {
    return parseMode(window.localStorage.getItem(MODE_STORAGE_KEY) ?? chosen);
  } catch {
    return chosen ?? DEFAULT_MODE;
  }
}

function subscribe(onChange: () => void): () => void {
  window.addEventListener("storage", onChange);
  window.addEventListener(CHANGE_EVENT, onChange);
  return () => {
    window.removeEventListener("storage", onChange);
    window.removeEventListener(CHANGE_EVENT, onChange);
  };
}

/**
 * 遊び方のモード(オフライン / オンライン)。選んだモードは閲覧者のブラウザに覚えておく。
 * 静的ビルドの描画(サーバー側)と最初の描画は既定のオフラインにする(ハイドレーションを揃えるため)。
 */
export function useAppMode(): [AppMode, (mode: AppMode) => void] {
  const mode = useSyncExternalStore(subscribe, read, () => DEFAULT_MODE);
  const setMode = useCallback((next: AppMode) => {
    chosen = next;
    try {
      window.localStorage.setItem(MODE_STORAGE_KEY, next);
    } catch {
      // 保存できなくても、この画面の中では切り替える
    }
    window.dispatchEvent(new Event(CHANGE_EVENT));
  }, []);
  return [mode, setMode];
}
