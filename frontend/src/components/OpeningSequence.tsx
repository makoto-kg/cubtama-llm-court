"use client";

import { useCallback, useMemo, useState } from "react";

import type { TrialView } from "@/api/client";
import { useDialogue } from "@/hooks/useDialogue";
import { defendantLabel, judgeLabel, prosecutorLabel } from "@/lib/roles";
import { type OpeningLine, OPENING_CUT_IN, openingScript, type OpeningSpeaker } from "@/lib/opening";
import { SUSPENSION_CUT_IN, suspensionScript, VERDICT_CUT_IN, verdictScript } from "@/lib/verdict";

import { CourtShot, type CourtShotKind, DialogueBox } from "./CourtScene";
import { CutInView } from "./CutIn";
import { GameShell } from "./GameShell";

/** 話す人ごとの法廷の画面。被告は証言台に立つ。 */
const SHOT: Record<OpeningSpeaker, CourtShotKind> = { judge: "judge", prosecutor: "prosecutor", defendant: "stand" };

/** 名札: 名前裁判長 / 名前検察官 / 名前被告。 */
function speakerName(speaker: OpeningSpeaker, view: TrialView): string {
  if (speaker === "prosecutor") return prosecutorLabel(view);
  if (speaker === "defendant") return defendantLabel(view);
  return judgeLabel();
}

/**
 * 台本どおりに話す法廷の場面(開廷・判決)。話す人ごとに画面を切り替え、台詞の前にカットインや木槌を入れる。
 * クリック・Enter・Space で台詞を送る(表示中なら全文を出す)。表示だけの場面で、ゲームの状態は変えない。
 */
function ScriptedScene({
  view,
  script,
  label,
  endCutIn,
  onFinish,
}: {
  view: TrialView;
  script: OpeningLine[];
  label: string;
  endCutIn: string;
  onFinish: () => void;
}) {
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
    if (ending) return { text: endCutIn, key: -1, strong: true };
    return holding && lineCutIn ? { text: lineCutIn, key: lineIndex, strong: true } : null;
  }, [ending, holding, lineCutIn, lineIndex, endCutIn]);
  const clearCutIn = useCallback(() => {
    if (ending) onFinish();
    else setCutInSeen(lineIndex);
  }, [ending, onFinish, lineIndex]);

  const line = script[dialogue.index];
  if (!line) return null;
  const name = speakerName(line.speaker, view);
  const showText = !holding || ending;
  const stage = (
      <CourtShot
        kind={SHOT[line.speaker]}
        alt={name}
        pose={line.pose}
        speaking={dialogue.typing}
        shake={Boolean(line.gavel) && showText}
      >
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
            <span className="min-w-0 truncate opacity-80">{label}</span>
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

/** 開廷の場面。裁判官の挨拶と事件の超概要・被告の紹介 → 検察官と被告の宣言 → 審理開始。 */
export function OpeningSequence({ view, onFinish }: { view: TrialView; onFinish: () => void }) {
  const script = useMemo(() => openingScript(view), [view]);
  return (
    <ScriptedScene
      view={view}
      script={script}
      label={`${view.case.title} — 開廷`}
      endCutIn={OPENING_CUT_IN.start}
      onFinish={onFinish}
    />
  );
}

/** 判決の場面(ADR 0020)。裁判官が有罪と刑罰を言い渡し、被告が反応する → 閉廷 → 裁判のまとめ。 */
export function VerdictSequence({ view, onFinish }: { view: TrialView; onFinish: () => void }) {
  const script = useMemo(() => verdictScript(view), [view]);
  return (
    <ScriptedScene
      view={view}
      script={script}
      label={`${view.case.title} — 判決`}
      endCutIn={VERDICT_CUT_IN.close}
      onFinish={onFinish}
    />
  );
}

/** 審理が中断した場面。ゲージが尽きたら、裁判官が中断を告げ、検察官が肩を落とす → 閉廷 → 裁判のまとめ。 */
export function SuspensionSequence({ view, onFinish }: { view: TrialView; onFinish: () => void }) {
  const script = useMemo(() => suspensionScript(view), [view]);
  return (
    <ScriptedScene
      view={view}
      script={script}
      label={`${view.case.title} — 審理中断`}
      endCutIn={SUSPENSION_CUT_IN.close}
      onFinish={onFinish}
    />
  );
}
