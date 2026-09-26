"""ディベート用のフェイク LLM 応答。"""

import json
from collections.abc import Callable
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


ADVOCATE_TEXT = "ご指摘します。「単純計算で年間約150兆円が必要になります」[EV-02]。"


def target_claim_ids(user: str) -> list[str]:
    """分析官プロンプトの「相手の直前の発言の主張」節から主張 ID を取り出す。"""
    section = user.split("# 相手の直前の発言の主張", 1)[1]
    return [line[2:].split(":", 1)[0] for line in section.splitlines() if line.startswith("- C-")]


def contradictions_json(targets: list[str], *, strengths: list[str] | None = None) -> str:
    strengths = strengths or ["strong", "weak", "trap"]
    candidates: list[dict[str, Any]] = []
    for i, strength in enumerate(strengths):
        candidates.append(
            {
                "target_claim_id": targets[0],
                "evidence_id": "ev-1" if i == 0 else None,
                "other_claim_id": "C-01" if i == 1 else None,
                "type": ["evidence_conflict", "self_contradiction", "logical_leap"][i % 3],
                "strength": strength,
                "pitch": f"{strength} の指摘です。",
                "rationale": f"{strength} と判断した理由です。",
            }
        )
    # 参照が不正な候補(捨てられる)
    candidates.append({**candidates[0], "target_claim_id": "C-99", "pitch": "不正な参照の指摘"})
    data = {
        "candidates": candidates,
        "probe": {"target_claim_id": targets[-1], "question": "その根拠を説明してください。"},
    }
    return json.dumps(data, ensure_ascii=False)


ARGUMENTS_JSON = json.dumps(
    {
        "arguments": [
            {"title": "データで押す", "pitch": "実験データを示す。", "evidence_ids": ["EV-01"]},
            {"title": "財源で押す", "pitch": "財源の規模を示す。", "evidence_ids": ["ev-2"]},
            {"title": "架空の論点", "pitch": "存在しない証拠。", "evidence_ids": ["EV-99"]},
        ]
    },
    ensure_ascii=False,
)


class DebateResponder:
    """役割(スキーマ名・プロンプト)に応じた応答を返す。"""

    def __init__(
        self,
        *,
        judge_scores: list[tuple[int, int]] | None = None,
        claims_json: str | None = None,
        contradictions: Callable[[list[str]], str] | None = None,
    ) -> None:
        self.judge_scores = list(judge_scores or [(8, 6), (8, 6)])
        self.claims_json = claims_json
        self.contradictions = contradictions or contradictions_json

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
        if name == "ContradictionOutput":
            return FakeResponse.text(
                self.contradictions(target_claim_ids(request.messages[-1].content))
            )
        if name == "ArgumentOutput":
            return FakeResponse.text(ARGUMENTS_JSON)
        if name == "CandidateVerdict":
            # 検証役: strong の指摘・機械検査の指摘は strong、それ以外(trap を含む)は weak
            pitch = request.messages[-1].content.rsplit("\n", 1)[-1]
            strength = "strong" if "strong" in pitch or "出典" in pitch else "weak"
            return FakeResponse.text(json.dumps({"strength": strength, "reason": "理由"}))
        system = request.messages[0].content
        if "代弁者" in system:
            return FakeResponse.text(ADVOCATE_TEXT)
        if "あなたの立場: 肯定側" in system:
            return FakeResponse.text(AFFIRMATIVE_TEXT)
        return FakeResponse.text(NEGATIVE_TEXT)
