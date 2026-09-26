"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import type { Side } from "@/api/client";
import { openSession, useTitleData } from "@/hooks/useApi";
import { SIDE_LABELS } from "@/lib/labels";

type Mode = "watch" | "play";
type EvidenceSource = "sample" | "upload" | "research";

const STATUS_LABELS: Record<string, string> = {
  awaiting_evidence: "証拠品待ち",
  ready: "開廷前",
  in_progress: "審理中",
  finished: "閉廷",
  aborted: "中断",
};

export function TitleScreen() {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>("play");
  const [side, setSide] = useState<Side>("negative");
  const [topic, setTopic] = useState("");
  const [rounds, setRounds] = useState(1);
  const [source, setSource] = useState<EvidenceSource>("sample");
  const [chosenSample, setChosenSample] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const { data, error: loadError } = useTitleData();
  const samples = data?.samples ?? [];
  const sessions = data?.sessions ?? [];
  const sample = chosenSample ?? samples[0]?.name ?? "";
  const error = submitError ?? (loadError && `API に接続できません(${loadError})`);

  function selectSample(name: string) {
    setChosenSample(name);
    const found = samples.find((s) => s.name === name);
    if (found) setTopic(found.topic);
  }

  // 同梱の捜査結果を読み込んだら、最初のテーマを入れておく
  const defaultTopic = samples[0]?.topic ?? "";
  if (!topic && defaultTopic && source === "sample" && chosenSample === null) {
    setTopic(defaultTopic);
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setSubmitError(null);
    try {
      if (source === "upload" && !file) throw new Error("捜査結果の JSON ファイルを選んでください");
      const sessionId = await openSession(
        topic,
        rounds,
        mode === "play" ? side : null,
        source === "sample"
          ? { source, name: sample }
          : source === "upload" && file
            ? { source, file }
            : { source: "research" },
      );
      router.push(`/court/?session=${sessionId}`);
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  }

  const field = "rounded border border-[var(--court-wood-light)] bg-black/30 px-3 py-2";

  return (
    <div className="grid gap-6 md:grid-cols-[2fr_1fr]">
      <form
        onSubmit={submit}
        className="space-y-5 rounded-lg border border-[var(--court-wood-light)] bg-[var(--court-wood)]/60 p-5"
      >
        <fieldset className="space-y-2">
          <legend className="font-bold">モード</legend>
          <div className="flex flex-wrap gap-4">
            <label className="flex items-center gap-2">
              <input type="radio" checked={mode === "play"} onChange={() => setMode("play")} />
              対戦(人間 vs LLM)
            </label>
            <label className="flex items-center gap-2">
              <input type="radio" checked={mode === "watch"} onChange={() => setMode("watch")} />
              観戦(LLM vs LLM)
            </label>
          </div>
          {mode === "play" && (
            <div className="flex items-center gap-3 text-sm">
              あなたの陣営:
              {(["affirmative", "negative"] as const).map((s) => (
                <label key={s} className="flex items-center gap-1">
                  <input type="radio" checked={side === s} onChange={() => setSide(s)} />
                  {SIDE_LABELS[s]}
                </label>
              ))}
            </div>
          )}
        </fieldset>

        <fieldset className="space-y-2">
          <legend className="font-bold">証拠品</legend>
          <div className="flex flex-wrap gap-4 text-sm">
            <label className="flex items-center gap-1">
              <input type="radio" checked={source === "sample"} onChange={() => setSource("sample")} />
              同梱の捜査結果
            </label>
            <label className="flex items-center gap-1">
              <input type="radio" checked={source === "upload"} onChange={() => setSource("upload")} />
              JSON ファイル
            </label>
            <label className="flex items-center gap-1">
              <input
                type="radio"
                checked={source === "research"}
                onChange={() => setSource("research")}
              />
              Web で捜査(SearXNG が必要)
            </label>
          </div>
          {source === "sample" && (
            <select className={field} value={sample} onChange={(e) => selectSample(e.target.value)}>
              {samples.map((s) => (
                <option key={s.name} value={s.name}>
                  {s.topic}(証拠品 {s.evidence_count} 件)
                </option>
              ))}
            </select>
          )}
          {source === "upload" && (
            <input
              type="file"
              accept="application/json"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          )}
        </fieldset>

        <label className="block space-y-1">
          <span className="font-bold">論題</span>
          <input
            className={`${field} w-full`}
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            placeholder="例: 日本はベーシックインカムを導入すべきか"
            required
          />
        </label>

        <label className="flex items-center gap-3">
          <span className="font-bold">反論の往復数</span>
          <input
            type="number"
            min={1}
            max={5}
            className={`${field} w-20`}
            value={rounds}
            onChange={(e) => setRounds(Number(e.target.value))}
          />
        </label>

        {error && <p className="text-sm text-red-300">{error}</p>}
        <button
          type="submit"
          disabled={busy || !topic}
          className="rounded bg-[var(--court-accent)] px-6 py-2 font-bold text-black disabled:opacity-50"
        >
          {busy ? "開廷準備中…" : "開廷"}
        </button>
      </form>

      <aside className="space-y-2">
        <h2 className="font-bold">最近の審理</h2>
        {sessions.length === 0 && <p className="text-sm opacity-70">まだありません</p>}
        <ul className="space-y-2">
          {sessions.map((s) => (
            <li key={s.session_id}>
              <Link
                href={`/court/?session=${s.session_id}`}
                className="block rounded border border-[var(--court-wood-light)] p-2 text-sm hover:bg-white/5"
              >
                <span className="block truncate">{s.topic}</span>
                <span className="text-xs opacity-70">
                  {STATUS_LABELS[s.status] ?? s.status} / {new Date(s.created_at).toLocaleString("ja-JP")}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      </aside>
    </div>
  );
}
