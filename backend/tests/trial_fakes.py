"""裁判(プレイ)用のフェイク LLM 応答と事件。"""

import json
from typing import Any

from llm_court.domain import Case, ResearchReport
from llm_court.llm import ChatRequest, PromptLoader
from tests.case_fakes import CaseResponder
from tests.debate_fakes import schema_name
from tests.fakes import FakeResponse

COLLAPSE_TEXT = "そ、そんな……。認めます、私の証言は間違っていました。"
EVADE_TEXT = "それは確かなことです。何度聞かれても同じです。"


def user_text(request: ChatRequest) -> str:
    return "\n".join(m.content for m in request.messages if m.role == "user")


class TrialResponder:
    """証人は台本の指示どおりに答え、判定役は応答の文言から自白を判定する。

    `confess_always` にすると、証人が常に自白する(早すぎる自白の逸脱)。
    """

    def __init__(self, *, confess_always: bool = False, leak: bool = False) -> None:
        self.confess_always = confess_always
        self.leak = leak
        self.requests: dict[str, list[ChatRequest]] = {}

    def __call__(self, request: ChatRequest) -> FakeResponse:
        name = schema_name(request) or "text"
        self.requests.setdefault(name, []).append(request)
        user = user_text(request)
        if name == "DeviationOutput":
            response = user.split("# 被告の応答", 1)[1]
            confessed = "認めます" in response
            data: dict[str, Any] = {
                # 応答にない引用は採用されない(2 件目の漏洩と、範囲外の番号は捨てられる)
                "confession_excerpt": "認めます、私の証言は間違っていました" if confessed else "",
                "leaks": [
                    {"index": 0, "excerpt": "私の証言は間違っていました"},
                    {"index": 1, "excerpt": "応答にない引用"},
                    {"index": 7, "excerpt": "私の証言は間違っていました"},
                ]
                if self.leak
                else [],
                "reason": "判定の理由です。",
            }
            return FakeResponse.text(json.dumps(data, ensure_ascii=False))
        if self.confess_always or "決定的なもの" in user:
            return FakeResponse.text(COLLAPSE_TEXT)
        return FakeResponse.text(EVADE_TEXT)


async def make_case(prompts: PromptLoader, report: ResearchReport) -> Case:
    """事件生成のフェイクで作った解ける事件(X-01: TS-01-2 × CE-01、X-02: TS-02-2 × CE-02)。"""
    from tests.unit.test_scenario import generate

    return await generate(prompts, report, CaseResponder())
