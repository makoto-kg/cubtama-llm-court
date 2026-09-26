"""分析官の候補精度の評価。

完了したディベートの反論・最終弁論の各発言について、相手側の立場から分析官に矛盾候補を
作らせ、検証役(judge 役)が各候補の強さを独立に判定する。
"""

import logging
from typing import Literal

from pydantic import BaseModel, ConfigDict

from llm_court.agents.analyst import AnalystAgent
from llm_court.agents.verifier import CandidateVerifier
from llm_court.domain import DebatePhase, Statement, Strength
from llm_court.engine.state import DebateState
from llm_court.llm import LLMConnectionError, LLMError

logger = logging.getLogger(__name__)

_TARGET_PHASES = (DebatePhase.REBUTTAL, DebatePhase.CLOSING)


class CandidateEval(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: str
    source: Literal["analyst", "rule"]
    analyst_strength: Strength
    verifier_strength: Strength | None
    """検証役の判定(失敗したら None)。"""


class CandidateSetEval(BaseModel):
    model_config = ConfigDict(frozen=True)

    statement_id: str
    success: bool
    discarded: int = 0
    candidates: list[CandidateEval] = []
    error: str | None = None


def _context_until(state: DebateState, statement: Statement) -> DebateState:
    """`statement` までの発言・主張・引用の問題だけを持つ状態(その時点の手番を再現する)。"""
    ids = {s.id for s in state.statements if s.turn <= statement.turn}
    return state.model_copy(
        update={
            "statements": [s for s in state.statements if s.id in ids],
            "claims": [c for c in state.claims if c.statement_id in ids],
            "citation_issues": [i for i in state.citation_issues if i.statement_id in ids],
        }
    )


async def evaluate_analyst(
    state: DebateState, analyst: AnalystAgent, verifier: CandidateVerifier
) -> list[CandidateSetEval]:
    assert state.topic is not None and state.session_id is not None
    results: list[CandidateSetEval] = []
    for statement in state.statements:
        if statement.phase not in _TARGET_PHASES:
            continue
        context = _context_until(state, statement)
        try:
            prepared = await analyst.contradictions(
                topic=state.topic,
                side=statement.side.opponent,
                target=statement,
                evidence=context.evidence,
                claims=context.claims,
                issues=context.citation_issues,
                id_prefix=f"E{statement.turn:02d}",
                seed=f"{state.session_id}-{statement.turn}",
            )
        except LLMConnectionError:
            raise
        except (LLMError, ValueError) as e:
            results.append(CandidateSetEval(statement_id=statement.id, success=False, error=str(e)))
            continue

        candidates: list[CandidateEval] = []
        for option in prepared.options:
            c = option.contradiction
            if c is None or c.strength is None or option.source is None:
                continue  # ゆさぶる
            verified: Strength | None = None
            try:
                verdict = await verifier.verify(
                    topic=state.topic,
                    candidate=c,
                    pitch=option.pitch,
                    claims=context.claims,
                    statements=context.statements,
                    evidence=context.evidence,
                )
                verified = verdict.value.strength
            except LLMConnectionError:
                raise
            except LLMError as e:
                logger.warning("候補の検証に失敗しました: %s", e)
            candidates.append(
                CandidateEval(
                    type=c.type,
                    source=option.source,
                    analyst_strength=c.strength,
                    verifier_strength=verified,
                )
            )
        results.append(
            CandidateSetEval(
                statement_id=statement.id,
                success=True,
                discarded=prepared.discarded,
                candidates=candidates,
            )
        )
    return results
