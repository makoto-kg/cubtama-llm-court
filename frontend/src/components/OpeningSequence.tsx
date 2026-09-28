"use client";

import { useCallback, useMemo, useState } from "react";

import type { TrialView } from "@/api/client";
import { SPEAKER_NAMES } from "@/assets/manifest";
import { useDialogue } from "@/hooks/useDialogue";
import { OPENING_CUT_IN, openingScript } from "@/lib/opening";

import { CourtShot, DialogueBox } from "./CourtScene";
import { CutInView } from "./CutIn";

/**
 * 開廷の場面。裁判長の挨拶と事件の超概要 → 原告側・被告側の宣言 → 審理開始。
 * クリック・Enter・Space で台詞を送る(表示中なら全文を出す)。表示だけの場面で、ゲームの状態は変えない。
 */
export function OpeningSequence({ view, onFinish }: { view: TrialView; onFinish: () => void }) {
  const script = useMemo(() => openingScript(view), [view]);
  const texts = useMemo(() => script.map((l) => l.text), [script]);
  // カットインを見せ終えた台詞の番号(その台詞のカットインが済むまで文字送りを止める)
  const [cutInSeen, setCutInSeen] = useState(-1);
  const [ending, setEnding] = useState(false);
  const dialogue = useDialogue({
    texts,
    hold: (i) => ending || (Boolean(script[i]?.cutIn) && cutInSeen < i),
    onEnd: () => setEnding(true),
  });
  const lineIndex = dialogue.index;
  const lineCutIn = script[lineIndex]?.cutIn;
  const holding = dialogue.hold;

  const cutIn = useMemo(() => {
    if (ending) return { text: OPENING_CUT_IN.start, key: -1, strong: true };
    return holding && lineCutIn ? { text: lineCutIn, key: lineIndex, strong: true } : null;
  }, [ending, holding, lineCutIn, lineIndex]);
  const clearCutIn = useCallback(() => {
    if (ending) onFinish();
    else setCutInSeen(lineIndex);
  }, [ending, onFinish, lineIndex]);

  const line = script[dialogue.index];
  if (!line) return null;
  const name = line.speaker === "plaintiff" ? `${SPEAKER_NAMES.plaintiff}(あなた)` : SPEAKER_NAMES[line.speaker];
  const showText = !holding || ending;
  return (
    <div className="space-y-2">
      <CutInView cutIn={cutIn} onDone={clearCutIn} />
      <div className="flex items-center justify-between text-xs opacity-80">
        <span>{view.case.title} — 開廷</span>
        <button onClick={onFinish} className="rounded border px-2 py-0.5">
          スキップ
        </button>
      </div>
      <CourtShot kind={line.speaker} alt={name} speaking={dialogue.typing} shake={Boolean(line.gavel) && showText}>
        {line.gavel && showText && (
          <span key={dialogue.index} className="gavel-sound absolute right-[8%] top-[8%] text-4xl font-black">
            カンッ!
          </span>
        )}
        <DialogueBox name={name} waiting={dialogue.done && !holding} onClick={dialogue.advance}>
          <span className={dialogue.typing ? "caret whitespace-pre-wrap" : "whitespace-pre-wrap"}>
            {showText ? dialogue.shown : ""}
          </span>
        </DialogueBox>
      </CourtShot>
      <p className="text-center text-xs opacity-60">クリック・Enter で次へ</p>
    </div>
  );
}
