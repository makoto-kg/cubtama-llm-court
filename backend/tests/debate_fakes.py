"""ディベート用のフェイク LLM 応答。"""

import json
from typing import Any

from llm_court.llm import ChatRequest
from tests.fakes import FakeResponse

AFFIRMATIVE_TEXT = "導入すべきです。実験では「雇用には大きな効果は見られなかった」のです[EV-01]。"
NEGATIVE_TEXT = (
    "導入すべきではありません。「年間約150兆円が必要になります」[EV-02]。架空の根拠[EV-09]。"
)
CLAIMS = {
    "claims": [
        {"text": "雇用への影響は小さい", "kind": "fact", "cited_evidence_ids": ["ev-1"]},
        {"text": "導入すべき", "kind": "value", "cited_evidence_ids": ["EV-99"]},
    ]
}


def judge_json(aff: int, neg: int) -> str:
    rationale = (
        "肯定側は証拠品を正確に引用して論理を組み立てた。否定側は財源の問題を具体的に示したが、"
        "存在しない証拠品を引用した点は減点した。"
    )
    data: dict[str, Any] = {
        "affirmative": {"logic": aff, "evidence": aff, "rebuttal": aff, "persuasiveness": aff},
        "negative": {"logic": neg, "evidence": neg, "rebuttal": neg, "persuasiveness": neg},
        "rationale": rationale,
    }
    return json.dumps(data, ensure_ascii=False)


def schema_name(request: ChatRequest) -> str | None:
    if request.response_format is None:
        return None
    return request.response_format["json_schema"]["name"]


class DebateResponder:
    """役割(スキーマ名・プロンプト)に応じた応答を返す。"""

    def __init__(
        self,
        *,
        judge_scores: list[tuple[int, int]] | None = None,
        claims_json: str | None = None,
    ) -> None:
        self.judge_scores = list(judge_scores or [(8, 6), (8, 6)])
        self.claims_json = claims_json

    def __call__(self, request: ChatRequest) -> FakeResponse:
        name = schema_name(request)
        if name == "ClaimList":
            claims = self.claims_json or json.dumps(CLAIMS, ensure_ascii=False)
            return FakeResponse.text(claims)
        if name == "JudgeOutput":
            # 提示順は並行実行されるため、プロンプトで判別する
            user = request.messages[-1].content
            first_aff = user.index("# 肯定側の弁論") < user.index("# 否定側の弁論")
            aff, neg = self.judge_scores[0] if first_aff else self.judge_scores[1]
            return FakeResponse.text(judge_json(aff, neg))
        system = request.messages[0].content
        if "あなたの立場: 肯定側" in system:
            return FakeResponse.text(AFFIRMATIVE_TEXT)
        return FakeResponse.text(NEGATIVE_TEXT)
