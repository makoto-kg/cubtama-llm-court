"""裁判型の分析官。尋問の選択肢を事件のデータから規則で組み立てる(LLM を使わない)。

正解と罠は事件のデータで既知なので、LLM に候補を考えさせる必要がない。候補は
正解・罠・はずれ(同じ証言の別の行や別の証拠品)・ゆさぶる で構成し、並び順は
`seed` で決まる順に混ぜる(同じセッション・同じ手番なら同じ順になる)。
"""

import random
from collections.abc import Collection

from llm_court.domain import Case, Strength, Testimony, TrialOption
from llm_court.modes import TrialMode


def _quote(text: str, limit: int = 40) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def present_label(line_text: str, evidence_name: str) -> str:
    return f"「{_quote(line_text)}」に「{evidence_name}」をつきつける"


def probe_label(line_text: str) -> str:
    return f"「{_quote(line_text)}」をゆさぶる"


class TrialAnalyst:
    def __init__(self, mode: TrialMode) -> None:
        self._mode = mode

    def prepare(
        self,
        *,
        case: Case,
        testimony: Testimony,
        solved: Collection[str],
        tried: Collection[tuple[str, str, str | None]],
        id_prefix: str,
        seed: str,
    ) -> list[TrialOption]:
        """現在の証言について選択肢を並べる。

        `tried` は選択済みの (kind, line_id, evidence_id)。同じ行動は二度並べない。
        """
        rng = random.Random(seed)
        # つきつけられるのは手元にある証拠品だけ
        # (尋問の中で手に入る証拠品は、手に入れてから。ADR 0019)
        available = case.available_evidence_ids(tried)
        evidence = {e.id: e for e in case.evidence if e.id in available}
        lines = {line.id: line for line in testimony.lines}
        contradictions = [
            c for c in case.contradictions if c.testimony_line_id in lines and c.id not in solved
        ]
        solved_lines = {c.testimony_line_id for c in case.contradictions if c.id in solved}
        options: list[TrialOption] = []
        used: set[tuple[str, str, str | None]] = set(tried)
        # まだ証拠品を手に入れていない行動は、無作為に選ばず必ず並べる(見逃して詰まらないように)
        unlock_actions = [
            u
            for u in case.evidence_unlocks
            if u.line_id in lines and u.line_id not in solved_lines and not u.triggered_by(tried)
        ]
        forced_probes = {u.line_id for u in unlock_actions if u.kind == "probe"}
        forced_presents = {
            (u.line_id, u.presented_evidence_id)
            for u in unlock_actions
            if u.kind == "present" and u.presented_evidence_id is not None
        }

        def present(
            line_id: str,
            evidence_id: str,
            strength: Strength,
            *,
            contradiction_id: str | None = None,
            trap_reason: str | None = None,
        ) -> None:
            key = ("present", line_id, evidence_id)
            if key in used or evidence_id not in evidence:
                return
            used.add(key)
            options.append(
                TrialOption(
                    id="",
                    kind="present",
                    line_id=line_id,
                    evidence_id=evidence_id,
                    label=present_label(lines[line_id].text, evidence[evidence_id].name),
                    strength=strength,
                    contradiction_id=contradiction_id,
                    trap_reason=trap_reason,
                )
            )

        # 1. 正解と罠
        for c in contradictions:
            present(c.testimony_line_id, c.evidence_id, "strong", contradiction_id=c.id)
            for trap in c.traps:
                if trap.evidence_id != c.evidence_id:
                    present(
                        c.testimony_line_id, trap.evidence_id, "trap", trap_reason=trap.why_tempting
                    )

        # 2. はずれ(正解・罠でない 行 × 証拠品 の組)
        correct = {(c.testimony_line_id, c.evidence_id) for c in case.contradictions}
        pairs = [
            (line_id, evidence_id)
            for line_id in lines
            if line_id not in solved_lines
            for evidence_id in evidence
            if (line_id, evidence_id) not in correct
            and (line_id, evidence_id) not in forced_presents
            and ("present", line_id, evidence_id) not in used
        ]
        rng.shuffle(pairs)
        for line_id, evidence_id in pairs[: self._mode.distractor_options]:
            present(line_id, evidence_id, "weak")
        for line_id, evidence_id in sorted(forced_presents):
            present(line_id, evidence_id, "weak")

        # 3. ゆさぶる(嘘の行を優先せず、未解決の行から無作為に選ぶ)
        probe_lines = [
            line_id
            for line_id in lines
            if line_id not in solved_lines
            and line_id not in forced_probes
            and ("probe", line_id, None) not in used
        ]
        rng.shuffle(probe_lines)
        for line_id in probe_lines[: self._mode.probe_options] + sorted(forced_probes):
            options.append(
                TrialOption(
                    id="",
                    kind="probe",
                    line_id=line_id,
                    label=probe_label(lines[line_id].text),
                )
            )

        rng.shuffle(options)
        return [
            o.model_copy(update={"id": f"{id_prefix}-{i}"}) for i, o in enumerate(options, start=1)
        ]
