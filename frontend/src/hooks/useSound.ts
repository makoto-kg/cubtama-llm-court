"use client";

import { useCallback, useEffect, useRef, useSyncExternalStore } from "react";

import { acquireBgm, syncBgm } from "@/lib/bgm";
import { blipDue, playBlip, setSoundEnabled, soundEnabled, SOUND_STORAGE_KEY } from "@/lib/sound";

const CHANGE_EVENT = "llm-court:sound-change";

function subscribe(onChange: () => void): () => void {
  const onStorage = (e: StorageEvent) => {
    if (e.key === SOUND_STORAGE_KEY) {
      setSoundEnabled(e.newValue !== "off");
      onChange();
    }
  };
  window.addEventListener("storage", onStorage);
  window.addEventListener(CHANGE_EVENT, onChange);
  return () => {
    window.removeEventListener("storage", onStorage);
    window.removeEventListener(CHANGE_EVENT, onChange);
  };
}

/** 効果音の有無(閲覧者のブラウザに覚えておく)。静的ビルドの描画と最初の描画は「出す」にする。 */
export function useSoundEnabled(): [boolean, (on: boolean) => void] {
  const on = useSyncExternalStore(subscribe, soundEnabled, () => true);
  const set = useCallback((next: boolean) => {
    setSoundEnabled(next);
    window.dispatchEvent(new Event(CHANGE_EVENT));
  }, []);
  return [on, set];
}

/** この部品が出ている間、音ありなら BGM を流す(どのページにも出ている見出しで使う)。音の切り替えにもついていく。 */
export function useBgm(): void {
  const [on] = useSoundEnabled();
  useEffect(() => acquireBgm(), []);
  useEffect(() => syncBgm(), [on]);
}

/**
 * 台詞を打ち出す間の文字送りの音。`shown` は今見えている台詞(打ち出した分)。
 * 文字が増えたときだけ鳴らし、打ち直し(短くなった)・全文の一括表示は 1 回だけ鳴らす。
 */
export function useTypingSound(shown: string): void {
  const prev = useRef(shown);
  const lastAt = useRef(0);
  useEffect(() => {
    const before = prev.current;
    prev.current = shown;
    if (shown.length <= before.length || !shown.startsWith(before)) return;
    const now = performance.now();
    if (blipDue(shown.slice(before.length), now - lastAt.current)) {
      lastAt.current = now;
      playBlip();
    }
  }, [shown]);
}
