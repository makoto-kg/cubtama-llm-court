"use client";

import type { SessionView } from "@/api/client";
import { useSessionReport } from "@/hooks/useApi";
import { RUBRIC_LABELS, SIDE_LABELS, STRENGTH_LABELS } from "@/lib/labels";

function seconds(ms: number | null | undefined): string {
  return ms == null ? "-" : `${(ms / 1000).toFixed(1)}s`;
}

/** 判決画面。勝者・採点・裁判長の理由・人間の選択・計測・法廷記録。 */
export function Verdict({ view }: { view: SessionView }) {
  const { data } = useSessionReport(view.session_id);
  const record = data?.record ?? null;
  const summary = data?.summary ?? null;
  const verdict = view.verdict;

  let result = "中断";
  if (verdict) {
    const winner = verdict.winner ? `${SIDE_LABELS[verdict.winner]}の勝ち` : "引き分け";
    if (view.human_side && verdict.winner) {
      result = verdict.winner === view.human_side ? `あなたの勝ち(${winner})` : `あなたの負け(${winner})`;
    } else {
      result = winner;
    }
  }

  return (
    <section className="space-y-5">
      <div className="rounded-lg border-2 border-[var(--court-accent)] bg-black/40 p-5 text-center">
        <p className="text-sm opacity-70">判決</p>
        <p className="text-3xl font-black text-[var(--court-accent)]">{result}</p>
        {verdict?.decided_by === "penalty" && <p className="mt-1">ペナルティゲージが尽きました</p>}
        {verdict && !verdict.agreed && verdict.decided_by === "judge" && (
          <p className="mt-1 text-sm opacity-80">提示順を入れ替えた評価で判定が割れたため引き分け</p>
        )}
        {view.aborted && <p className="mt-1 text-red-300">{view.aborted}</p>}
      </div>

      {view.judge_scores.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-white/20">
                <th className="p-1 text-left">評価</th>
                <th className="p-1 text-left">陣営</th>
                {Object.values(RUBRIC_LABELS).map((label) => (
                  <th key={label} className="p-1">
                    {label}
                  </th>
                ))}
                <th className="p-1">合計</th>
              </tr>
            </thead>
            <tbody>
              {view.judge_scores.flatMap((score, i) =>
                (["affirmative", "negative"] as const).map((side) => {
                  const values = score.scores[side] ?? {};
                  const total = Object.values(values).reduce((a, b) => a + b, 0);
                  return (
                    <tr key={`${i}-${side}`} className="border-b border-white/10">
                      <td className="p-1">
                        {i + 1}({score.order.map((s) => SIDE_LABELS[s]).join("→")})
                      </td>
                      <td className="p-1">{SIDE_LABELS[side]}</td>
                      {Object.keys(RUBRIC_LABELS).map((key) => (
                        <td key={key} className="p-1 text-center tabular-nums">
                          {values[key] ?? "-"}
                        </td>
                      ))}
                      <td className="p-1 text-center font-bold tabular-nums">{total}</td>
                    </tr>
                  );
                }),
              )}
            </tbody>
          </table>
        </div>
      )}

      {verdict && (
        <div>
          <h3 className="font-bold">裁判長の理由</h3>
          <p className="whitespace-pre-wrap text-sm">{verdict.rationale}</p>
        </div>
      )}

      {view.choices.length > 0 && (
        <div>
          <h3 className="font-bold">あなたの選択</h3>
          <ul className="space-y-1 text-sm">
            {view.choices.map((c) => {
              const strength = c.contradiction?.strength;
              return (
                <li key={c.id}>
                  {c.label}
                  {strength && (
                    <span className="ml-2 rounded bg-white/10 px-1">{STRENGTH_LABELS[strength] ?? strength}</span>
                  )}
                  {c.contradiction?.rationale && (
                    <span className="block pl-4 text-xs opacity-70">{c.contradiction.rationale}</span>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {summary && (
        <div className="text-sm">
          <h3 className="font-bold">計測</h3>
          <p>
            LLM 呼び出し {summary.llm_calls} 回 / 出力 {summary.output_tokens} tok / 構造化出力の失敗{" "}
            {summary.structured_failures} / 所要 {summary.wall_time_s?.toFixed(0) ?? "-"}s
          </p>
          <ul className="mt-1 grid grid-cols-2 gap-1 md:grid-cols-3">
            {summary.turns.map((t) => (
              <li key={t.statement_id} className="rounded bg-black/30 px-2 text-xs">
                {t.statement_id} {SIDE_LABELS[t.side]}: TTFT {seconds(t.ttft_ms)} / 計 {seconds(t.total_ms)}
              </li>
            ))}
          </ul>
        </div>
      )}

      {record && (
        <details>
          <summary className="cursor-pointer font-bold">法廷記録(Markdown)</summary>
          <pre className="mt-2 max-h-[40rem] overflow-auto whitespace-pre-wrap rounded bg-black/40 p-3 text-xs">
            {record}
          </pre>
        </details>
      )}
    </section>
  );
}
