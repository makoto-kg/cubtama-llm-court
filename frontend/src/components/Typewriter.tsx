"use client";

import { useEffect, useRef, useState } from "react";

import { nextVisibleLength } from "@/lib/typewriter";

/**
 * タイプライター表示。`text` が伸びる(ストリーミング)たびに続きを表示する。
 * `resetKey` が変わったら最初から表示し直す(別の発言)。
 * `paused` の間(カットインの最中など)は文字を送らない。届いた分は再開後に追いつく速さで表示する。
 * 全文を出し終え、ストリーミングも終わったら `onDone` を呼ぶ(同じ発言で何度か呼ぶことがある)。
 */
export function Typewriter({
  text,
  resetKey,
  active,
  paused = false,
  onDone,
}: {
  text: string;
  resetKey: string;
  active: boolean;
  paused?: boolean;
  onDone?: () => void;
}) {
  const [visible, setVisible] = useState(0);
  const [prevKey, setPrevKey] = useState(resetKey);
  const last = useRef<number | null>(null);

  if (prevKey !== resetKey) {
    setPrevKey(resetKey);
    setVisible(0);
  }

  useEffect(() => {
    if (paused) {
      // 止めていた時間を経過時間に数えない
      last.current = null;
      return;
    }
    if (visible >= text.length) return;
    let frame = 0;
    const tick = (now: number) => {
      const elapsed = last.current === null ? 16 : now - last.current;
      last.current = now;
      setVisible((v) => nextVisibleLength(v, text.length, elapsed));
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [paused, visible, text.length]);

  const finished = !paused && !active && prevKey === resetKey && visible >= text.length;
  useEffect(() => {
    if (finished) onDone?.();
  }, [finished, onDone]);

  const typing = !paused && (visible < text.length || active);
  return (
    <span className={typing ? "caret whitespace-pre-wrap" : "whitespace-pre-wrap"}>
      {text.slice(0, visible)}
    </span>
  );
}
