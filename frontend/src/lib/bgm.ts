import { BGM } from "@/assets/manifest";

import { soundEnabled } from "./sound";

/**
 * BGM(ADR 0023)。音ありなら、どのページでもくり返し流す(見出しの `HeaderNav` から `useBgm` で使う)。
 * 曲が頭に戻らないよう、要素は 1 つを使い回し、使う部品が消えてから少し待って止める。止めたところから再開する。
 */

/** BGM を使う部品が消えてから止めるまでの待ち(ms)。すぐ出し直されれば止めない。 */
const RELEASE_DELAY_MS = 400;

let audio: HTMLAudioElement | null = null;
let users = 0;
let releaseTimer: ReturnType<typeof setTimeout> | null = null;
let waitingGesture = false;

function element(): HTMLAudioElement {
  if (!audio) {
    audio = new Audio(BGM.src);
    audio.loop = true;
    audio.volume = BGM.volume;
    audio.preload = "auto";
  }
  return audio;
}

/** ブラウザが操作の前の再生を止めたときは、最初のタップ・キー入力のあとに流し直す。 */
function retryOnGesture(): void {
  if (waitingGesture) return;
  waitingGesture = true;
  const retry = () => {
    waitingGesture = false;
    window.removeEventListener("pointerdown", retry);
    window.removeEventListener("keydown", retry);
    syncBgm();
  };
  window.addEventListener("pointerdown", retry);
  window.addEventListener("keydown", retry);
}

/** BGM を使う部品が出ていて音ありなら流し、そうでなければ止める。 */
export function syncBgm(): void {
  if (users === 0 || !soundEnabled()) {
    audio?.pause();
    return;
  }
  const el = element();
  if (!el.paused) return;
  el.play().catch(retryOnGesture);
}

/** BGM を使う部品が出たときに呼ぶ。返した関数を部品が消えるときに呼ぶ。 */
export function acquireBgm(): () => void {
  users += 1;
  if (releaseTimer) clearTimeout(releaseTimer);
  releaseTimer = null;
  syncBgm();
  return () => {
    users -= 1;
    if (releaseTimer) clearTimeout(releaseTimer);
    releaseTimer = setTimeout(syncBgm, RELEASE_DELAY_MS);
  };
}
