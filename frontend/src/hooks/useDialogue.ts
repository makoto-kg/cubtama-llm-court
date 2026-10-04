"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { useTypingSound } from "@/hooks/useSound";
import { isAdvanceKey } from "@/lib/keys";
import { nextVisibleLength } from "@/lib/typewriter";

/**
 * 台詞の列を 1 つずつタイプライター表示で送る(開廷の場面・証言の読み上げ)。
 * - `advance`: 表示中なら全文を出し、読み終わっていれば次の台詞へ。最後の台詞の後で `onEnd` を 1 回呼ぶ
 * - `hold` の間(カットインなど)は文字送りも操作も止める。台詞の番号ごとに決めるなら関数で渡す
 * - 自動では進めない。読み終えたらクリック・タップ・Enter・Space を待つ
 * - Enter・Space でも `advance` する
 * - 文字を打ち出す間は文字送りの音を鳴らす(ADR 0023)
 */
export function useDialogue({
  texts,
  hold: holdOption = false,
  charsPerSecond = 30,
  onEnd,
}: {
  texts: string[];
  hold?: boolean | ((index: number) => boolean);
  charsPerSecond?: number;
  onEnd: () => void;
}) {
  const [index, setIndex] = useState(0);
  const [visible, setVisible] = useState(0);
  const [ended, setEnded] = useState(false);
  const last = useRef<number | null>(null);

  const hold = typeof holdOption === "function" ? holdOption(index) : holdOption;
  const text = texts[index] ?? "";
  const done = visible >= text.length;
  const shown = text.slice(0, visible);
  useTypingSound(shown);

  useEffect(() => {
    if (hold || done || ended) return;
    const frame = requestAnimationFrame((now) => {
      const elapsed = last.current === null ? 16 : now - last.current;
      last.current = now;
      setVisible((v) => nextVisibleLength(v, text.length, elapsed, charsPerSecond));
    });
    return () => cancelAnimationFrame(frame);
  }, [hold, done, ended, visible, text.length, charsPerSecond]);

  const advance = useCallback(() => {
    if (hold || ended) return;
    if (!done) {
      setVisible(text.length);
      return;
    }
    last.current = null;
    if (index + 1 >= texts.length) {
      setEnded(true);
      onEnd();
      return;
    }
    setIndex(index + 1);
    setVisible(0);
  }, [hold, ended, done, text.length, index, texts.length, onEnd]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (isAdvanceKey(e)) {
        e.preventDefault();
        advance();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [advance]);

  return { index, text, shown, typing: !done && !hold && !ended, done, ended, hold, advance };
}
