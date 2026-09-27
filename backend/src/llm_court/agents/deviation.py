"""証人の応答が台本から逸脱していないかの判定(judge 役)。

LLM には事実の判定(自白したか・どの隠している事実を漏らしたか)だけをさせ、
それが逸脱かどうか(崩れるべき場面だったか)はコードで決める。誤検出を減らすため、
自白・漏洩の箇所を応答から引用させ、その引用が実際に応答の中にあるものだけを採用する。
"""

from pydantic import BaseModel, Field

from llm_court.agents.witness import script_for
from llm_court.config import Role
from llm_court.domain import Case, DeviationCheck, DeviationKind, Testimony, TrialOption
from llm_court.llm import LLMClient, LLMConnectionError, LLMError, PromptLoader
from llm_court.research.quotes import verify_quote


class LeakedFact(BaseModel):
    index: int = Field(description="隠している事実の番号(0 始まり)")
    excerpt: str = Field(min_length=1, description="その事実を明かしている箇所の、応答からの引用")


class DeviationOutput(BaseModel):
    confession_excerpt: str = Field(
        description="偽りの証言の誤りを認めた箇所の、応答からの引用。認めていなければ空文字"
    )
    leaks: list[LeakedFact] = []
    reason: str = Field(min_length=1)


def deviations_of(
    *, confessed: bool, leaked: list[int], should_collapse: bool
) -> list[DeviationKind]:
    kinds: list[DeviationKind] = []
    if confessed and not should_collapse:
        kinds.append("premature_confession")
    if should_collapse and not confessed:
        kinds.append("failed_collapse")
    if leaked and not should_collapse:
        kinds.append("leak")  # 崩れる場面で真相に触れるのは台本どおり
    return kinds


class DeviationChecker:
    def __init__(self, llm: LLMClient, prompts: PromptLoader) -> None:
        self._llm = llm
        self._prompts = prompts

    async def check(
        self,
        *,
        case: Case,
        testimony: Testimony,
        option: TrialOption,
        response: str,
        should_collapse: bool,
    ) -> DeviationCheck | None:
        """判定できなかった場合は None(失敗は LLM 呼び出しの記録に残る)。"""
        script = script_for(case, testimony.witness_id)
        lies = [lie for lie in case.hidden_truth.lies if lie.witness_id == testimony.witness_id]
        prompt = self._prompts.render(
            "judge/witness_deviation",
            lies=lies,
            hidden_facts=script.hidden_facts,
            testimony=testimony,
            action=option.label,
            response=response,
        )
        try:
            result = await self._llm.generate_structured(Role.JUDGE, prompt, DeviationOutput)
        except LLMConnectionError:
            raise
        except LLMError:
            return None
        out = result.value
        # 応答の中にない引用は採用しない(判定役の思い込みによる誤検出を除く)
        excerpt = out.confession_excerpt.strip()
        confessed = bool(excerpt) and verify_quote(excerpt, response)
        leaked = sorted(
            {
                leak.index
                for leak in out.leaks
                if 0 <= leak.index < len(script.hidden_facts)
                and verify_quote(leak.excerpt, response)
            }
        )
        return DeviationCheck(
            confessed=confessed,
            leaked_fact_indices=leaked,
            deviations=deviations_of(
                confessed=confessed, leaked=leaked, should_collapse=should_collapse
            ),
            reason=out.reason,
        )
