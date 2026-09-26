"use client";

import { useState } from "react";

import type { LLMCallInfo } from "@/api/client";
import { ROLE_LABELS } from "@/lib/labels";

function seconds(ms: number | null | undefined): string {
  return ms == null ? "-" : `${(ms / 1000).toFixed(1)}s`;
}

const HIDDEN = "(選択後に公開)";

function Block({ title, children }: { title: string; children: string }) {
  return (
    <div>
      <p className="text-xs font-bold opacity-70">{title}</p>
      <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded bg-black/40 p-2 text-xs">{children}</pre>
    </div>
  );
}

function CallRow({ call }: { call: LLMCallInfo }) {
  const [open, setOpen] = useState(false);
  const hidden = call.messages != null && call.response_text == null;
  return (
    <li className="rounded border border-white/10">
      <button onClick={() => setOpen((o) => !o)} className="w-full p-2 text-left text-xs hover:bg-white/5">
        <span className={`mr-2 ${call.success ? "text-emerald-300" : "text-red-300"}`}>
          {call.success ? "●" : "✗"}
        </span>
        <span className="font-bold">{ROLE_LABELS[call.role] ?? call.role}</span>
        <span className="ml-2 opacity-70">{call.prompt_name ?? call.kind}</span>
        <span className="float-right tabular-nums opacity-80">
          TTFT {seconds(call.ttft_ms)} / 計 {seconds(call.total_ms)} / 出力 {call.output_tokens ?? "-"} tok
          {call.tokens_per_s != null && ` / ${call.tokens_per_s.toFixed(0)} tok/s`}
          {call.retries > 0 && ` / 再試行 ${call.retries}`}
        </span>
      </button>
      {open && (
        <div className="space-y-2 border-t border-white/10 p-2">
          <p className="text-xs opacity-70">
            モデル {call.model}({call.model_key})/ プロンプト {call.prompt_name ?? "-"}@
            {call.prompt_version ?? "-"} / 入力 {call.input_tokens ?? "-"} tok
            {call.structured_mode && ` / 構造化 ${call.structured_mode}`}
            {call.error && ` / エラー: ${call.error}`}
          </p>
          {call.messages?.map((m, i) => (
            <Block key={i} title={`入力(${m.role})`}>
              {m.content}
            </Block>
          ))}
          {call.reasoning_text && <Block title="思考">{call.reasoning_text}</Block>}
          <Block title="生出力">{hidden ? HIDDEN : (call.response_text ?? "(記録なし)")}</Block>
          {(call.parsed || hidden) && (
            <Block title="パース結果">{hidden ? HIDDEN : JSON.stringify(call.parsed, null, 2)}</Block>
          )}
        </div>
      )}
    </li>
  );
}

/** 思考ログ(書記官の記録)。LLM への入力・生出力・パース結果・トークン数・レイテンシ。 */
export function ThinkingLog({ calls }: { calls: LLMCallInfo[] }) {
  return (
    <section className="rounded-lg border border-[var(--court-wood-light)] bg-black/30 p-3">
      <h2 className="mb-2 font-bold">書記官の記録(思考ログ)</h2>
      {calls.length === 0 && <p className="text-sm opacity-70">まだ記録はありません</p>}
      <ul className="max-h-[32rem] space-y-1 overflow-y-auto">
        {[...calls].reverse().map((call) => (
          <CallRow key={call.call_id} call={call} />
        ))}
      </ul>
    </section>
  );
}
