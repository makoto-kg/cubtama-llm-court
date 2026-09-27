import type { OfflinePack } from "@/api/client";

import { presentKey, probeKey } from "../engine";

const EVIDENCE = ["CE-01", "CE-02", "CE-03", "CE-04"];
const TESTIMONIES = [
  { id: "TS-00", witness_id: "P-01", title: "矛盾のない証言", lines: [{ id: "TS-00-1", text: "何もありません" }] },
  {
    id: "TS-01",
    witness_id: "P-02",
    title: "担当者の証言",
    lines: [
      { id: "TS-01-1", text: "結果は 4 月 2 日に届きました" },
      { id: "TS-01-2", text: "実験では就業率が半分に落ちました" },
    ],
  },
  {
    id: "TS-02",
    witness_id: "P-03",
    title: "予算担当の証言",
    lines: [
      { id: "TS-02-1", text: "試算は会議室で行いました" },
      { id: "TS-02-2", text: "年間 10 兆円あれば全員に配れます" },
    ],
  },
];
const CORRECT = new Set([presentKey("TS-01-2", "CE-01"), presentKey("TS-02-2", "CE-02")]);

/** テスト用の小さなパック(矛盾 X-01: TS-01-2 × CE-01、X-02: TS-02-2 × CE-02)。 */
export function makePack(gauge = 5): OfflinePack {
  const responses: OfflinePack["responses"] = [];
  for (const t of TESTIMONIES.slice(1)) {
    for (const line of t.lines) {
      const keys = [probeKey(line.id), ...EVIDENCE.map((e) => presentKey(line.id, e))];
      for (const key of keys) {
        const collapse = CORRECT.has(key);
        responses.push({
          key,
          witness_id: t.witness_id,
          text: collapse ? `崩れた(${key})` : `言い逃れ(${key})`,
          should_collapse: collapse,
          check: { confessed: collapse, leaked_fact_indices: [], deviations: [], reason: "r" },
          attempts: 1,
          call: null,
        });
      }
    }
  }
  return {
    format_version: 1,
    theme: "給付",
    case: {
      id: "case1",
      title: "給付事業報告書事件",
      overview: "概要",
      question: { text: "誰が偽ったか", options: ["監査役", "担当者", "誰も"] },
      people: [
        { id: "P-01", name: "朝霧 透", role: "依頼人", description: "" },
        { id: "P-02", name: "白波 恵", role: "証人", description: "" },
        { id: "P-03", name: "黒川 誠", role: "証人", description: "" },
      ],
      evidence: EVIDENCE.map((id, i) => ({ id, name: `証拠品${i + 1}`, description: "", details: [] })),
      testimonies: TESTIMONIES,
    },
    answers: {
      contradictions: [
        {
          id: "X-01",
          testimony_line_id: "TS-01-2",
          evidence_id: "CE-01",
          traps: [{ evidence_id: "CE-03", why_tempting: "誤解があるから" }],
        },
        { id: "X-02", testimony_line_id: "TS-02-2", evidence_id: "CE-02", traps: [] },
      ],
      answer_index: 1,
    },
    explanation: {
      title: "給付事業報告書事件",
      truth: "真相",
      question: "誰が偽ったか",
      answer: "担当者",
      items: [],
      learning_points: [],
    },
    mode: {
      penalty_gauge: gauge,
      penalties: { strong: 0, weak: 1, trap: 2 },
      distractor_options: 2,
      probe_options: 2,
    },
    responses,
    meta: {
      generated_at: "2026-09-27T00:00:00Z",
      models: { witness: "small" },
      prompt_versions: {},
      responses: responses.length,
      deviations: 0,
      unchecked: 0,
    },
  };
}
