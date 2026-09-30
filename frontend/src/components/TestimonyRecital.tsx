"use client";

import { useCallback, useMemo, useState } from "react";

import type { TrialView } from "@/api/client";
import { useDialogue } from "@/hooks/useDialogue";
import { speakerLabel } from "@/lib/roles";
import { TESTIMONY_CUT_IN } from "@/lib/trial";

import { CourtShot, DialogueBox } from "./CourtScene";
import { CutInView } from "./CutIn";

type Testimony = TrialView["case"]["testimonies"][number];

/**
 * 証言の読み上げ。「証言開始」→ 被告が証言の行を 1 行ずつ話す → 「尋問開始」。
 * 読み上げが終わるまで尋問の操作は出さない(`onFinish` で尋問へ移る)。表示だけで、ゲームの状態は変えない。
 */
export function TestimonyRecital({
  view,
  testimony,
  onFinish,
}: {
  view: TrialView;
  testimony: Testimony;
  onFinish: () => void;
}) {
  const texts = useMemo(() => testimony.lines.map((l) => `「${l.text}」`), [testimony]);
  const [started, setStarted] = useState(false);
  const [ending, setEnding] = useState(false);
  const dialogue = useDialogue({
    texts,
    hold: !started || ending,
    onEnd: () => setEnding(true),
  });
  const cutIn = useMemo(() => {
    if (!started) return { text: TESTIMONY_CUT_IN.start, key: 0, strong: false };
    if (ending) return { text: TESTIMONY_CUT_IN.examine, key: 1, strong: false };
    return null;
  }, [started, ending]);
  const clearCutIn = useCallback(() => {
    if (ending) onFinish();
    else setStarted(true);
  }, [ending, onFinish]);

  const witnessName = speakerLabel(view, testimony.witness_id);
  return (
    <div className="space-y-2">
      <CutInView cutIn={cutIn} onDone={clearCutIn} />
      <CourtShot kind="stand" alt={witnessName} speaking={dialogue.typing}>
        <div className="absolute inset-x-0 top-3 text-center">
          <span className="testimony-title rounded px-4 py-1 text-sm font-bold sm:text-base">
            〜 {testimony.title} 〜
          </span>
        </div>
        <DialogueBox name={witnessName} waiting={started && dialogue.done && !ending} onClick={dialogue.advance}>
          <span className={`testimony-text whitespace-pre-wrap ${dialogue.typing ? "caret" : ""}`}>
            {started ? dialogue.shown : ""}
          </span>
          <span className="absolute -top-6 right-1 rounded bg-black/60 px-2 text-xs">
            {Math.min(dialogue.index + 1, texts.length)}/{texts.length}
          </span>
        </DialogueBox>
      </CourtShot>
      <div className="flex items-center justify-between gap-2 text-xs opacity-70">
        <span className="min-w-0 truncate">証言を聞いています(タップで次へ)</span>
        <button onClick={onFinish} className="shrink-0 rounded border px-2 py-0.5">
          尋問へ ▶
        </button>
      </div>
    </div>
  );
}
