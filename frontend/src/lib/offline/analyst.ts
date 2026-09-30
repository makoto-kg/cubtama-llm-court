import type { OfflinePack, TrialOption } from "@/api/client";

import { createRandom, shuffle } from "./prng";

/**
 * 規則の分析官(backend の `agents/trial_analyst.py` の移植)。
 * 正解・罠・はずれ・ゆさぶる を並べ、seed で決まる順に混ぜる。
 */

type Testimony = OfflinePack["case"]["testimonies"][number];
type Strength = NonNullable<TrialOption["strength"]>;
type Unlock = OfflinePack["answers"]["unlocks"][number];

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

/** 証拠品を手に入れる行動の識別(`triedKey` と同じ形)。 */
function unlockKey(u: Unlock): string {
  return triedKey({
    kind: u.kind,
    line_id: u.line_id,
    evidence_id: u.kind === "present" ? (u.presented_evidence_id ?? null) : null,
  });
}

/** 尋問の中で手に入る証拠品と、手に入れる行動(古いパックにはない)。 */
export function unlocksOf(pack: OfflinePack): Unlock[] {
  return pack.answers.unlocks ?? [];
}

/**
 * 選択済みの行動のあとで手元にある証拠品(backend の `Case.available_evidence_ids`。ADR 0019)。
 * 尋問の中で手に入る証拠品は、手に入れる行動を取るまで含めない。
 */
export function availableEvidenceIds(pack: OfflinePack, tried: ReadonlySet<string>): Set<string> {
  const locked = new Set(
    unlocksOf(pack)
      .filter((u) => !tried.has(unlockKey(u)))
      .map((u) => u.evidence_id),
  );
  return new Set(pack.case.evidence.map((e) => e.id).filter((id) => !locked.has(id)));
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
  // つきつけられるのは手元にある証拠品だけ(尋問の中で手に入る証拠品は、手に入れてから)
  const available = availableEvidenceIds(pack, tried);
  const evidence = new Map(pack.case.evidence.filter((e) => available.has(e.id)).map((e) => [e.id, e]));
  const lines = new Map(testimony.lines.map((l) => [l.id, l]));
  const all = pack.answers.contradictions;
  const contradictions = all.filter((c) => lines.has(c.testimony_line_id) && !solved.has(c.id));
  const solvedLines = new Set(all.filter((c) => solved.has(c.id)).map((c) => c.testimony_line_id));
  const used = new Set(tried);
  const options: TrialOption[] = [];
  // まだ証拠品を手に入れていない行動は、無作為に選ばず必ず並べる(見逃して詰まらないように)
  const unlockActions = unlocksOf(pack).filter(
    (u) => lines.has(u.line_id) && !solvedLines.has(u.line_id) && !tried.has(unlockKey(u)),
  );
  const forcedProbes = [...new Set(unlockActions.filter((u) => u.kind === "probe").map((u) => u.line_id))].sort();
  const forcedPresents: [string, string][] = unlockActions
    .filter((u) => u.kind === "present" && u.presented_evidence_id)
    .map((u) => [u.line_id, u.presented_evidence_id!] as [string, string])
    .sort((a, b) => (a[0] === b[0] ? (a[1] < b[1] ? -1 : a[1] > b[1] ? 1 : 0) : a[0] < b[0] ? -1 : 1));
  const forcedPresentKeys = new Set(forcedPresents.map(([l, e]) => `${l}|${e}`));

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
      if (!correct.has(`${lineId}|${evidenceId}`) && !forcedPresentKeys.has(`${lineId}|${evidenceId}`) && !used.has(key)) {
        pairs.push([lineId, evidenceId]);
      }
    }
  }
  for (const [lineId, evidenceId] of shuffle(pairs, random).slice(0, pack.mode.distractor_options)) {
    present(lineId, evidenceId, "weak");
  }
  for (const [lineId, evidenceId] of forcedPresents) present(lineId, evidenceId, "weak");

  // 3. ゆさぶる(未解決の行から無作為に)
  const probeLines = [...lines.keys()].filter(
    (lineId) =>
      !solvedLines.has(lineId) &&
      !forcedProbes.includes(lineId) &&
      !used.has(triedKey({ kind: "probe", line_id: lineId })),
  );
  for (const lineId of [...shuffle(probeLines, random).slice(0, pack.mode.probe_options), ...forcedProbes]) {
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
