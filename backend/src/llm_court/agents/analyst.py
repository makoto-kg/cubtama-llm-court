"""分析官。人間の手番に示す選択肢(矛盾候補・ゆさぶる・論点の方針)を作る。"""

import random
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator

from llm_court.config import Role
from llm_court.domain import (
    ChoiceOption,
    CitationIssue,
    Claim,
    ContradictionCandidate,
    ContradictionType,
    DebatePhase,
    Evidence,
    Side,
    Statement,
    Strength,
    normalize_evidence_ids,
)
from llm_court.llm import LLMClient, LLMConnectionError, LLMError, PromptLoader
from llm_court.modes import DebateMode

_LABEL_CHARS = 30


class CandidateDraft(BaseModel):
    target_claim_id: str
    evidence_id: str | None = None
    other_claim_id: str | None = None
    type: ContradictionType
    strength: Strength
    pitch: str = Field(min_length=5, max_length=300)
    rationale: str = Field(min_length=5, max_length=400)


class ProbeDraft(BaseModel):
    target_claim_id: str
    question: str = Field(min_length=5, max_length=200)


class ContradictionOutput(BaseModel):
    candidates: list[CandidateDraft] = Field(min_length=3, max_length=5)
    probe: ProbeDraft

    @model_validator(mode="after")
    def _mixed(self) -> Self:
        strengths = {c.strength for c in self.candidates}
        if "strong" not in strengths:
            raise ValueError("strong の候補を 1 つ以上含めてください")
        if not strengths & {"weak", "trap"}:
            raise ValueError("weak または trap の候補を 1 つ以上含めてください")
        return self


class ArgumentDraft(BaseModel):
    title: str = Field(min_length=2, max_length=60)
    pitch: str = Field(min_length=5, max_length=300)
    evidence_ids: list[str] = Field(min_length=1)


class ArgumentOutput(BaseModel):
    arguments: list[ArgumentDraft] = Field(min_length=2, max_length=5)


@dataclass(frozen=True)
class PreparedChoices:
    options: list[ChoiceOption]
    discarded: int
    """参照が不正で捨てた候補の数。"""
    prompt_version: str | None
    fell_back: bool = False
    """矛盾候補を作れず、論点の方針に切り替えたか。"""


def _short(text: str, limit: int = _LABEL_CHARS) -> str:
    return text if len(text) <= limit else text[:limit] + "…"


class AnalystAgent:
    def __init__(self, llm: LLMClient, prompts: PromptLoader, mode: DebateMode) -> None:
        self._llm = llm
        self._prompts = prompts
        self._mode = mode

    def _type_label(self, key: str) -> str:
        return self._mode.contradiction_types.get(key, key).split("(")[0]

    async def prepare(
        self,
        *,
        topic: str,
        side: Side,
        phase: DebatePhase,
        evidence: Sequence[Evidence],
        claims: Sequence[Claim],
        statements: Sequence[Statement],
        issues: Sequence[CitationIssue],
        id_prefix: str,
        seed: str,
    ) -> PreparedChoices:
        """`side`(人間側)の手番の選択肢を作る。"""
        target = next((s for s in reversed(statements) if s.side is side.opponent), None)
        if self._mode.choice_kinds.get(phase) == "contradiction" and target is not None:
            try:
                return await self.contradictions(
                    topic=topic,
                    side=side,
                    target=target,
                    evidence=evidence,
                    claims=claims,
                    issues=issues,
                    id_prefix=id_prefix,
                    seed=seed,
                )
            except LLMConnectionError:
                raise
            except (LLMError, ValueError):
                # 矛盾候補を作れなければ論点の方針で続ける(試合を止めない)
                prepared = await self.arguments(
                    topic=topic,
                    side=side,
                    phase=phase,
                    evidence=evidence,
                    claims=claims,
                    id_prefix=id_prefix,
                )
                return PreparedChoices(
                    options=prepared.options,
                    discarded=prepared.discarded,
                    prompt_version=prepared.prompt_version,
                    fell_back=True,
                )
        return await self.arguments(
            topic=topic,
            side=side,
            phase=phase,
            evidence=evidence,
            claims=claims,
            id_prefix=id_prefix,
        )

    async def contradictions(
        self,
        *,
        topic: str,
        side: Side,
        target: Statement,
        evidence: Sequence[Evidence],
        claims: Sequence[Claim],
        issues: Sequence[CitationIssue],
        id_prefix: str,
        seed: str,
    ) -> PreparedChoices:
        """相手の発言 `target` の主張に対する矛盾候補と「ゆさぶる」を作る。

        参照が不正な候補は捨てる。有効な矛盾候補が 2 つ未満なら `ValueError`。
        """
        claim_by_id = {c.id: c for c in claims}
        target_claims = [c for c in claims if c.statement_id == target.id]
        if not target_claims:  # 主張抽出に失敗した発言は、相手のこれまでの主張を対象にする
            target_claims = [c for c in claims if c.side is target.side]
        if not target_claims:
            raise ValueError("つきつける対象の主張がありません")
        target_ids = {c.id for c in target_claims}
        evidence_by_id = {e.id: e for e in evidence}

        prompt = self._prompts.render(
            "analyst/contradictions",
            topic=topic,
            side_label=side.label,
            opponent_label=side.opponent.label,
            contradiction_types=self._mode.contradiction_types,
            count_min=self._mode.contradiction_count[0],
            count_max=self._mode.contradiction_count[1],
            evidence=evidence,
            claims=claims,
            target_statement=target,
            target_claims=target_claims,
        )
        result = await self._llm.generate_structured(Role.ANALYST, prompt, ContradictionOutput)

        # (候補, プレイヤーに見せる要旨, 由来)
        candidates: list[tuple[ContradictionCandidate, str, Literal["analyst", "rule"]]] = []
        discarded = 0
        for draft in result.value.candidates:
            evidence_id = (
                (normalize_evidence_ids([draft.evidence_id]) or [draft.evidence_id])[0]
                if draft.evidence_id
                else None
            )
            if (
                draft.target_claim_id not in target_ids
                or (evidence_id is not None and evidence_id not in evidence_by_id)
                or (draft.other_claim_id is not None and draft.other_claim_id not in claim_by_id)
            ):
                discarded += 1
                continue
            candidate = ContradictionCandidate(
                target_claim_id=draft.target_claim_id,
                evidence_id=evidence_id,
                other_claim_id=draft.other_claim_id,
                type=draft.type,
                strength=draft.strength,
                rationale=draft.rationale,
            )
            candidates.append((candidate, draft.pitch, "analyst"))

        # 機械検査で見つかった引用の問題は、規則で strong の候補にする
        for issue in issues:
            if issue.statement_id != target.id or issue.kind not in (
                "unknown_evidence",
                "unsupported_quote",
            ):
                continue
            citing = [c for c in target_claims if issue.evidence_id in c.cited_evidence_ids]
            claim = (citing or target_claims)[0]
            candidate = ContradictionCandidate(
                target_claim_id=claim.id,
                evidence_id=issue.evidence_id if issue.evidence_id in evidence_by_id else None,
                type="fabricated_citation",
                strength="strong",
                rationale=f"機械検査で検出: {issue.detail}",
            )
            pitch = f"この主張の出典は証拠品と一致しない。{issue.detail}"
            candidates.append((candidate, pitch, "rule"))

        if len(candidates) < 2:
            raise ValueError("有効な矛盾候補が足りません")

        options = [
            ChoiceOption(
                id="",
                kind="contradiction",
                label=self._contradiction_label(c, claim_by_id, evidence_by_id),
                pitch=pitch,
                contradiction=c,
                source=source,
            )
            for c, pitch, source in candidates
        ]
        # 強さが並び順から推測されないようにセッション・手番ごとに決まった順で混ぜる
        random.Random(seed).shuffle(options)

        probe = result.value.probe
        if probe.target_claim_id in claim_by_id:
            claim = claim_by_id[probe.target_claim_id]
            options.append(
                ChoiceOption(
                    id="",
                    kind="probe",
                    label=f"{claim.statement_id} の主張「{_short(claim.text)}」をゆさぶる",
                    pitch=probe.question,
                    target_claim_id=claim.id,
                )
            )
        else:
            discarded += 1

        return PreparedChoices(
            options=[
                o.model_copy(update={"id": f"{id_prefix}-{i}"})
                for i, o in enumerate(options, start=1)
            ],
            discarded=discarded,
            prompt_version=result.record.prompt_version,
        )

    async def arguments(
        self,
        *,
        topic: str,
        side: Side,
        phase: DebatePhase,
        evidence: Sequence[Evidence],
        claims: Sequence[Claim],
        id_prefix: str,
    ) -> PreparedChoices:
        """冒頭陳述・最終弁論などで取れる論点の方針を作る。"""
        known = {e.id for e in evidence}
        prompt = self._prompts.render(
            "analyst/arguments",
            topic=topic,
            side_label=side.label,
            phase_label=phase.label,
            count=self._mode.argument_count,
            evidence=evidence,
            claims=claims,
        )
        result = await self._llm.generate_structured(Role.ANALYST, prompt, ArgumentOutput)
        options: list[ChoiceOption] = []
        discarded = 0
        for draft in result.value.arguments:
            ids = [i for i in normalize_evidence_ids(draft.evidence_ids) if i in known]
            if not ids:
                discarded += 1
                continue
            options.append(
                ChoiceOption(
                    id=f"{id_prefix}-{len(options) + 1}",
                    kind="argument",
                    label=draft.title,
                    pitch=draft.pitch,
                    evidence_ids=ids,
                )
            )
        if not options:
            raise ValueError("有効な論点の方針がありません")
        return PreparedChoices(
            options=options, discarded=discarded, prompt_version=result.record.prompt_version
        )

    def _contradiction_label(
        self,
        candidate: ContradictionCandidate,
        claims: dict[str, Claim],
        evidence: dict[str, Evidence],
    ) -> str:
        target = claims[candidate.target_claim_id]
        if candidate.evidence_id is not None:
            thrust = (
                f"{candidate.evidence_id}「{_short(evidence[candidate.evidence_id].title, 20)}」"
            )
        elif candidate.other_claim_id is not None:
            other = claims[candidate.other_claim_id]
            thrust = f"{other.statement_id} の主張「{_short(other.text, 20)}」"
        else:
            thrust = "論理の筋道"
        return (
            f"{target.statement_id} の主張「{_short(target.text)}」に{thrust}をつきつける"
            f"({self._type_label(candidate.type)})"
        )
