import type { OfflinePack, TrialOption } from "@/api/client";

import { createRandom, shuffle } from "./prng";

/**
 * 規則の分析官(backend の `agents/trial_analyst.py` の移植)。
 * 正解・罠・はずれ・ゆさぶる を並べ、seed で決まる順に混ぜる。
 */

type Testimony = OfflinePack["case"]["testimonies"][number];
type Strength = NonNullable<TrialOption["strength"]>;

function quote(text: string, limit = 40): string {
  return text.length <= limit ? text : text.slice(0, limit - 1) + "…";
}

export function presentLabel(lineText: string, evidenceName: string): string {
  return `「${quote(lineText)}」に「${evidenceName}」をつきつける`;
}

export function probeLabel(lineText: string): string {
  return `「${quote(lineText)}」をゆさぶる`;
}

/** 選んだ行動の識別(同じ行動は二度並べない)。 */
export function triedKey(option: Pick<TrialOption, "kind" | "line_id" | "evidence_id">): string {
  return `${option.kind}:${option.line_id}:${option.evidence_id ?? ""}`;
}

export function prepareOptions({
  pack,
  testimony,
  solved,
  tried,
  idPrefix,
  seed,
}: {
  pack: OfflinePack;
  testimony: Testimony;
  solved: ReadonlySet<string>;
  tried: ReadonlySet<string>;
  idPrefix: string;
  seed: string;
}): TrialOption[] {
  const random = createRandom(seed);
  const evidence = new Map(pack.case.evidence.map((e) => [e.id, e]));
  const lines = new Map(testimony.lines.map((l) => [l.id, l]));
  const all = pack.answers.contradictions;
  const contradictions = all.filter((c) => lines.has(c.testimony_line_id) && !solved.has(c.id));
  const solvedLines = new Set(all.filter((c) => solved.has(c.id)).map((c) => c.testimony_line_id));
  const used = new Set(tried);
  const options: TrialOption[] = [];

  const present = (
    lineId: string,
    evidenceId: string,
    strength: Strength,
    extra: { contradiction_id?: string; trap_reason?: string } = {},
  ) => {
    const key = triedKey({ kind: "present", line_id: lineId, evidence_id: evidenceId });
    const ev = evidence.get(evidenceId);
    const line = lines.get(lineId);
    if (used.has(key) || !ev || !line) return;
    used.add(key);
    options.push({
      id: "",
      kind: "present",
      line_id: lineId,
      evidence_id: evidenceId,
      label: presentLabel(line.text, ev.name),
      strength,
      contradiction_id: extra.contradiction_id ?? null,
      trap_reason: extra.trap_reason ?? null,
    });
  };

  // 1. 正解と罠
  for (const c of contradictions) {
    present(c.testimony_line_id, c.evidence_id, "strong", { contradiction_id: c.id });
    for (const trap of c.traps) {
      if (trap.evidence_id !== c.evidence_id) {
        present(c.testimony_line_id, trap.evidence_id, "trap", { trap_reason: trap.why_tempting });
      }
    }
  }

  // 2. はずれ(正解・罠でない 行 × 証拠品 の組)
  const correct = new Set(all.map((c) => `${c.testimony_line_id}|${c.evidence_id}`));
  const pairs: [string, string][] = [];
  for (const lineId of lines.keys()) {
    if (solvedLines.has(lineId)) continue;
    for (const evidenceId of evidence.keys()) {
      const key = triedKey({ kind: "present", line_id: lineId, evidence_id: evidenceId });
      if (!correct.has(`${lineId}|${evidenceId}`) && !used.has(key)) pairs.push([lineId, evidenceId]);
    }
  }
  for (const [lineId, evidenceId] of shuffle(pairs, random).slice(0, pack.mode.distractor_options)) {
    present(lineId, evidenceId, "weak");
  }

  // 3. ゆさぶる(未解決の行から無作為に)
  const probeLines = [...lines.keys()].filter(
    (lineId) => !solvedLines.has(lineId) && !used.has(triedKey({ kind: "probe", line_id: lineId })),
  );
  for (const lineId of shuffle(probeLines, random).slice(0, pack.mode.probe_options)) {
    options.push({
      id: "",
      kind: "probe",
      line_id: lineId,
      evidence_id: null,
      label: probeLabel(lines.get(lineId)!.text),
      strength: null,
      contradiction_id: null,
      trap_reason: null,
    });
  }

  return shuffle(options, random).map((o, i) => ({ ...o, id: `${idPrefix}-${i + 1}` }));
}
