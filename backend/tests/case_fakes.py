"""事件生成用のフェイク LLM 応答(conftest の research_report と整合する)。"""

import json
from collections.abc import Callable
from typing import Any

from llm_court.llm import ChatRequest
from tests.debate_fakes import schema_name
from tests.fakes import FakeResponse

LEARNING_POINTS: dict[str, Any] = {
    "points": [
        {
            "knowledge": "給付実験では雇用への大きな影響は見られなかった",
            "explanation": "就労意欲が大きく下がるという懸念は実験では確認されていない。",
            "fact_keys": ["EV-01-f1"],
            "misconception": "給付を受けると誰も働かなくなる",
        },
        {
            "knowledge": "全国民に月10万円を配ると年間約150兆円が必要",
            "explanation": "財源の規模を見積もるときの基準になる。",
            "fact_keys": ["ev-2-f1"],
            "misconception": "既存の予算の組み替えだけで賄える",
            "outdated": True,
            "outdated_belief": "少額の予算で実施できるとされていた",
        },
        {
            "knowledge": "出典が確認できない知識",
            "explanation": "検証済みの事実に存在しない出典を指す。",
            "fact_keys": ["EV-01-f9"],
            "misconception": "出典のない誤解の例",
        },
    ]
}

HIDDEN_TRUTH: dict[str, Any] = {
    "summary": "町の給付事業の担当者が、実験結果と予算の数字を偽って報告していた。",
    "people": [
        {"key": "p1", "name": "朝霧 透", "role": "監査役", "description": "事業の監査役"},
        {"key": "p2", "name": "白波 恵", "role": "被告(担当者)", "description": "事業の担当者"},
        {"key": "p3", "name": "黒川 誠", "role": "関係者", "description": "予算の担当者"},
    ],
    "defendant_key": "p2",
    "timeline": [
        {
            "key": "t1",
            "order": 1,
            "time": "4月1日",
            "location": "役場",
            "person_keys": ["p1"],
            "description": "監査が始まる",
        },
        {
            "key": "t2",
            "order": 2,
            "time": "4月2日",
            "location": "役場",
            "person_keys": ["p2"],
            "description": "実験結果が届く",
        },
        {
            "key": "t3",
            "order": 3,
            "time": "4月3日",
            "location": "会議室",
            "person_keys": ["p2", "p3"],
            "description": "予算を試算する",
        },
        {
            "key": "t4",
            "order": 4,
            "time": "4月4日",
            "location": "役場",
            "person_keys": ["p1", "p2"],
            "description": "報告会",
        },
    ],
    "lies": [
        {
            "false_claim": "実験で就業率が半減した",
            "truth_event_key": "t2",
            "learning_point_ids": ["LP-01"],
        },
        {
            "false_claim": "年間10兆円で実施できる",
            "truth_event_key": "t3",
            "learning_point_ids": ["LP-02"],
        },
    ],
}

MATERIALS: dict[str, Any] = {
    "title": "給付事業報告書事件",
    "overview": "町の給付事業の報告書に不審な点があり、事業の担当者が被告として法廷に立った。",
    "question": {
        "text": "被告が報告書で偽った内容は何か",
        "options": ["監査の日程", "実験結果と予算の数字", "報告会の出席者"],
        "answer_index": 1,
    },
    "evidence": [
        {
            "key": "e1",
            "name": "実験結果の速報",
            "description": "就業状況の集計",
            "details": ["就業日数は対照群と差がない"],
        },
        {
            "key": "e2",
            "name": "予算試算メモ",
            "description": "給付額の試算",
            "details": ["月10万円×人口"],
        },
        {"key": "e3", "name": "議事録", "description": "報告会の記録", "details": ["出席者 3 名"]},
        {"key": "e4", "name": "日程表", "description": "監査の日程", "details": ["4月1日開始"]},
    ],
    "testimonies": [
        {
            "title": "実験結果についての証言",
            "lines": [
                {"text": "結果は 4 月 2 日に届きました", "lie_id": None},
                {"text": "実験では就業率が半分に落ちました", "lie_id": "L-01"},
            ],
        },
        {
            "title": "予算についての証言",
            "lines": [
                {"text": "試算は会議室で行いました", "lie_id": None},
                {"text": "年間 10 兆円あれば全員に配れます", "lie_id": "L-02"},
            ],
        },
    ],
    "script": {"persona": "早口", "hidden_facts": ["速報を読んでいる", "桁を偽った"]},
    "contradictions": [
        {
            "lie_id": "L-01",
            "evidence_key": "e1",
            "learning_point_ids": ["LP-01"],
            "explanation": "実験では雇用への影響は小さいので、就業率の半減は速報と食い違う。",
            "witness_reaction": "黙り込む",
        },
        {
            "lie_id": "L-02",
            "evidence_key": "e2",
            "learning_point_ids": ["LP-02"],
            "explanation": "月10万円を全国民に配ると年約150兆円必要で、10兆円では足りない。",
            "witness_reaction": "計算をやり直す",
        },
    ],
}

TRAPS: dict[str, Any] = {
    "traps": [
        {
            "contradiction_id": "X-01",
            "evidence_id": "CE-03",
            "reasoning": "議事録で働かなくなったと分かる",
            "learning_point_id": "LP-01",
            "why_tempting": "給付で働かなくなるという誤解があるから",
        },
        {
            "contradiction_id": "X-01",
            "evidence_id": "CE-01",
            "reasoning": "正解の証拠品(捨てられる)",
            "learning_point_id": "LP-01",
            "why_tempting": "正解と同じ",
        },
        {
            "contradiction_id": "X-02",
            "evidence_id": "CE-04",
            "reasoning": "日程表から予算が足りると分かる",
            "learning_point_id": "LP-02",
            "why_tempting": "予算の組み替えで賄えるという誤解があるから",
        },
    ]
}

SOLVED: dict[str, Any] = {
    "accusations": [
        {"testimony_line_id": "TS-01-2", "evidence_id": "CE-01", "reasoning": "速報と食い違う"},
        {"testimony_line_id": "TS-02-2", "evidence_id": "CE-02", "reasoning": "桁が合わない"},
    ],
    "answer_index": 1,
}

UNSOLVED: dict[str, Any] = {
    "accusations": [{"testimony_line_id": "TS-01-1", "evidence_id": "CE-04", "reasoning": "日付"}],
    "answer_index": 0,
}


NO_LEAKS: dict[str, Any] = {"leaks": []}

LEAK: dict[str, Any] = {
    "leaks": [
        {
            "lie_id": "L-01",
            "excerpt": "報告書に不審な点があり",
            "reason": "報告書の誤りを示唆している",
        },
        {"lie_id": "L-02", "excerpt": "概要にない引用", "reason": "採用されない"},
        {"lie_id": "L-09", "excerpt": "監査役", "reason": "存在しない嘘"},
    ]
}


def text(data: dict[str, Any]) -> FakeResponse:
    return FakeResponse.text(json.dumps(data, ensure_ascii=False))


class CaseResponder:
    """スキーマ名ごとに応答を返す。`overrides` に関数を入れると、呼び出し回数に応じて変えられる。"""

    def __init__(
        self, overrides: dict[str, Callable[[int, ChatRequest], FakeResponse]] | None = None
    ) -> None:
        self.overrides = overrides or {}
        self.calls: dict[str, int] = {}
        self.requests: dict[str, list[ChatRequest]] = {}

    def __call__(self, request: ChatRequest) -> FakeResponse:
        name = schema_name(request) or "text"
        n = self.calls.get(name, 0)
        self.calls[name] = n + 1
        self.requests.setdefault(name, []).append(request)
        if name in self.overrides:
            return self.overrides[name](n, request)
        return text(
            {
                "LearningPointsOutput": LEARNING_POINTS,
                "HiddenTruthOutput": HIDDEN_TRUTH,
                "MaterialsOutput": MATERIALS,
                "TrapsOutput": TRAPS,
                "SolverOutput": SOLVED,
                "LeakCheckOutput": NO_LEAKS,
            }[name]
        )
