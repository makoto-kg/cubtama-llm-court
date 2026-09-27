"""公開する文(概要・問い)が、嘘の答え(真相)を明かしていないかの検査。

規則では意味の漏れを判定できないため、LLM(judge 役)に判定させる。誤検出を減らすため、
漏れている箇所を公開する文から引用させ、その引用が実際に文中にあるものだけを採用する。
"""

from pydantic import BaseModel, Field

from llm_court.config import Role
from llm_court.domain import Case, CheckIssue
from llm_court.llm import LLMClient, LLMConnectionError, LLMError, PromptLoader
from llm_court.research.quotes import verify_quote


class LeakDraft(BaseModel):
    lie_id: str
    excerpt: str = Field(min_length=1, description="答えを明かしている箇所の、公開する文からの引用")
    reason: str = Field(min_length=1)


class LeakCheckOutput(BaseModel):
    leaks: list[LeakDraft]


def public_text(case: Case) -> str:
    """検査対象の公開する文(概要と問い)。選択肢と証拠品は答えを含んでよいので除く。"""
    return f"{case.overview}\n{case.question.text}"


class LeakChecker:
    def __init__(self, llm: LLMClient, prompts: PromptLoader) -> None:
        self._llm = llm
        self._prompts = prompts

    async def check(self, case: Case) -> list[CheckIssue]:
        events = {e.id: e for e in case.hidden_truth.timeline}
        lies = [
            {
                "id": lie.id,
                "false_claim": lie.false_claim,
                "truth": events[lie.truth_event_id].description
                if lie.truth_event_id in events
                else "",
            }
            for lie in case.hidden_truth.lies
        ]
        prompt = self._prompts.render(
            "judge/overview_leak",
            overview=case.overview,
            question=case.question.text,
            lies=lies,
        )
        try:
            result = await self._llm.generate_structured(Role.JUDGE, prompt, LeakCheckOutput)
        except LLMConnectionError:
            raise
        except LLMError:
            return []  # 判定できなかった場合は通す(失敗は計測記録に残る)
        text = public_text(case)
        known = {lie.id for lie in case.hidden_truth.lies}
        issues: list[CheckIssue] = []
        for leak in result.value.leaks:
            if leak.lie_id not in known or not verify_quote(leak.excerpt, text):
                continue  # 文中にない引用・存在しない嘘は採用しない
            issues.append(
                CheckIssue(
                    code="overview_leak",
                    message=(
                        f"公開する概要・問いの「{leak.excerpt}」が、"
                        f"嘘 {leak.lie_id} の答えを明かしています({leak.reason})。"
                        "概要には事件の状況だけを書き、証言の真偽や真相は書かないでください"
                    ),
                    step="materials",
                )
            )
        return issues
