"use client";

import { useCallback, useMemo, useState } from "react";

import type { TrialView } from "@/api/client";
import { TRIAL_ROLE_NAMES } from "@/assets/manifest";
import { useDialogue } from "@/hooks/useDialogue";
import { defendantOf, OPENING_CUT_IN, openingScript, type OpeningSpeaker } from "@/lib/opening";

import { CourtShot, type CourtShotKind, DialogueBox } from "./CourtScene";
import { CutInView } from "./CutIn";
import { GameShell } from "./GameShell";

/** 話す人ごとの法廷の画面。被告は証言台に立つ。 */
const SHOT: Record<OpeningSpeaker, CourtShotKind> = { judge: "judge", prosecutor: "prosecutor", defendant: "stand" };

function speakerName(speaker: OpeningSpeaker, defendantName: string | null): string {
  if (speaker === "prosecutor") return `${TRIAL_ROLE_NAMES.prosecutor}(あなた)`;
  if (speaker === "defendant") return defendantName ?? TRIAL_ROLE_NAMES.defendant;
  return TRIAL_ROLE_NAMES.judge;
}

/**
 * 開廷の場面。裁判官の挨拶と事件の超概要・被告の紹介 → 検察官と被告の宣言 → 審理開始。
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
  const name = speakerName(line.speaker, defendantOf(view)?.name ?? null);
  const showText = !holding || ending;
  const stage = (
      <CourtShot kind={SHOT[line.speaker]} alt={name} speaking={dialogue.typing} shake={Boolean(line.gavel) && showText}>
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
  );
  return (
    <>
      <CutInView cutIn={cutIn} onDone={clearCutIn} />
      <GameShell
        top={
          <div className="flex items-center justify-between gap-2 text-xs">
            <span className="min-w-0 truncate opacity-80">{view.case.title} — 開廷</span>
            <button onClick={onFinish} className="shrink-0 rounded border px-3 py-1">
              スキップ
            </button>
          </div>
        }
        stage={stage}
        panel={<p className="text-center text-xs opacity-60">タップ・Enter で次へ</p>}
      />
    </>
  );
}
