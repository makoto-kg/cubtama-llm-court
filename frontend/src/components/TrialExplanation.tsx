"use client";

import { type FormEvent, useState } from "react";

import type { Explanation, ObjectionTarget, TrialView } from "@/api/client";
import { objectionTargets, RESULT_LABELS } from "@/lib/trial";

/** 「解説に異議あり」のフォーム。解説の項目を選んでコメントを送る。 */
function ObjectionForm({
  explanation,
  onSubmit,
}: {
  explanation: Explanation;
  onSubmit: (kind: ObjectionTarget, id: string, comment: string) => Promise<void>;
}) {
  const targets = objectionTargets(explanation);
  const [target, setTarget] = useState(0);
  const [comment, setComment] = useState("");
  const [sent, setSent] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const t = targets[target];
    if (!t || !comment.trim()) return;
    await onSubmit(t.kind, t.id, comment.trim());
    setComment("");
    setSent(true);
  }

  return (
    <form onSubmit={submit} className="space-y-2 rounded border border-red-400/40 bg-black/30 p-3">
      <p className="font-bold text-red-300">解説に異議あり</p>
      <p className="text-xs opacity-70">
        解説の誤り(出典と合わない、罠が不自然 など)を見つけたら、項目を選んで送ってください。
      </p>
      <select
        className="w-full rounded border border-[var(--court-wood-light)] bg-black/30 px-2 py-1 text-sm"
        value={target}
        onChange={(e) => setTarget(Number(e.target.value))}
        aria-label="異議を申し立てる項目"
      >
        {targets.map((t, i) => (
          <option key={`${t.kind}-${t.id}`} value={i}>
            {t.label}
          </option>
        ))}
      </select>
      <textarea
        className="w-full rounded border border-[var(--court-wood-light)] bg-black/30 px-2 py-1 text-sm"
        rows={3}
        maxLength={1000}
        value={comment}
        onChange={(e) => {
          setComment(e.target.value);
          setSent(false);
        }}
        placeholder="どこがおかしいか"
        aria-label="異議の内容"
      />
      <div className="flex items-center gap-3">
        <button
          type="submit"
          disabled={!comment.trim()}
          className="rounded bg-red-500 px-4 py-1 text-sm font-bold text-black disabled:opacity-50"
        >
          異議あり!
        </button>
        {sent && <span className="text-xs text-emerald-300">記録しました</span>}
      </div>
    </form>
  );
}

/** 閉廷後の解説(事件のデータから組み立てたもの。出典付き)。 */
export function TrialExplanation({
  view,
  onObject,
}: {
  view: TrialView;
  onObject: (kind: ObjectionTarget, id: string, comment: string) => Promise<void>;
}) {
  const explanation = view.explanation;
  if (!explanation) return null;
  const lps = new Map(explanation.learning_points.map((lp) => [lp.id, lp]));
  const result = view.result ?? "penalty";
  return (
    <section className="space-y-4">
      <div className="rounded-lg border-2 border-[var(--court-accent)] bg-black/50 p-4 text-center">
        <p className="text-sm opacity-70">閉廷</p>
        <p className={`text-3xl font-black ${result === "solved" ? "text-[var(--court-accent)]" : "text-red-300"}`}>
          {RESULT_LABELS[result] ?? result}
        </p>
        <p className="mt-1 text-sm">
          解いた矛盾 {view.solved_count}/{view.contradiction_count}
          {view.answer_index != null &&
            ` / 問いの答え: ${view.case.question.options[view.answer_index]}(${view.answer_correct ? "正解" : "不正解"})`}
        </p>
      </div>

      <div className="space-y-2 rounded-lg bg-black/30 p-4">
        <h2 className="text-lg font-bold">解説</h2>
        <p>
          <span className="mr-2 rounded bg-white/10 px-1 text-xs">真相</span>
          {explanation.truth}
        </p>
        <p>
          <span className="mr-2 rounded bg-white/10 px-1 text-xs">問い</span>
          {explanation.question} → <span className="font-bold">{explanation.answer}</span>
        </p>
      </div>

      {explanation.items.map((item) => (
        <article key={item.contradiction_id} className="space-y-2 rounded-lg border border-[var(--court-wood-light)] p-4">
          <p className="font-bold">
            {item.witness_name}の証言「{item.testimony_line}」
            <span className="mx-1 text-[var(--court-accent)]">×</span>
            {item.evidence_name}
          </p>
          <p className="text-sm">{item.explanation}</p>
          {item.learning_point_ids.map((id) => {
            const lp = lps.get(id);
            if (!lp) return null;
            return (
              <div key={id} className="rounded bg-sky-900/30 p-2 text-sm">
                <p>
                  <span className="mr-2 rounded bg-sky-400/30 px-1 text-xs">決め手の知識</span>
                  <span className="font-bold">{lp.knowledge}</span>
                </p>
                <p className="mt-1 opacity-90">{lp.explanation}</p>
                {lp.outdated && lp.outdated_belief && (
                  <p className="mt-1 text-amber-300">以前の通説: {lp.outdated_belief}(最近覆った知識です)</p>
                )}
                <ul className="mt-1 space-y-1 text-xs opacity-80">
                  {lp.sources.map((s, i) => (
                    <li key={i}>
                      出典:{" "}
                      {s.url ? (
                        <a href={s.url} target="_blank" rel="noreferrer" className="underline">
                          {s.title}
                        </a>
                      ) : (
                        // 台本の事件(チュートリアル)は、事件の証拠品を出典にする(URL なし)
                        s.title
                      )}
                      「{s.quote}」
                    </li>
                  ))}
                </ul>
              </div>
            );
          })}
          {item.traps.length > 0 && (
            <div className="space-y-1 text-sm">
              {item.traps.map((trap) => (
                <p key={trap.evidence_id} className="rounded bg-red-900/20 p-2">
                  <span className="mr-2 rounded bg-red-400/30 px-1 text-xs">罠</span>
                  {trap.evidence_name}: {trap.reasoning}
                  <span className="block text-xs opacity-80">
                    選びたくなる理由: {trap.why_tempting}
                    {trap.misconception && `(よくある誤解: ${trap.misconception})`}
                  </span>
                </p>
              ))}
            </div>
          )}
        </article>
      ))}

      <ObjectionForm explanation={explanation} onSubmit={onObject} />
      {view.objections.length > 0 && (
        <ul className="space-y-1 text-xs opacity-80">
          {view.objections.map((o) => (
            <li key={o.seq}>
              異議({o.target_id}): {o.comment}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
