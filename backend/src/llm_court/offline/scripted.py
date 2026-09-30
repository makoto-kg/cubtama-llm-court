"""台本のパック: 人が書いた事件と証人の応答から、LLM を使わずにオフラインパックを作る。

チュートリアルのように、応答を一字一句決めておきたい事件に使う(ADR 0016)。
シナリオファイル(YAML)には事件の全体(`Case`)と、起こりうる全行動に対する応答を書く。
応答の過不足・事件の不整合はパックを作る前にエラーにする。
"""

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

from llm_court.domain import Case
from llm_court.engine.explanation import build_explanation
from llm_court.modes import TrialMode
from llm_court.offline.models import OfflineMeta, OfflinePack, OfflineResponse
from llm_court.offline.simulate import enumerate_actions, pack_answers, pack_mode
from llm_court.scenario.checks import check_case


class ScriptedScenarioError(ValueError):
    pass


class ScriptedScenario(BaseModel):
    model_config = ConfigDict(frozen=True)

    tutorial: bool = False
    """チュートリアル(一覧の先頭に出す)。"""
    case: Case
    responses: dict[str, str]
    """行動キー(`present:<行>:<証拠品>` / `probe:<行>`)→ 証人の応答。"""


def load_scenario(path: Path) -> ScriptedScenario:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return ScriptedScenario.model_validate(data)


def validate_scenario(scenario: ScriptedScenario, mode: TrialMode) -> list[str]:
    """事件の整合性と、応答の過不足を調べる(問題の説明の列。空なら問題なし)。"""
    # 台本の事件は大きさを自由にしてよいので、嘘(矛盾)の数の範囲を緩める
    lies = len(scenario.case.hidden_truth.lies)
    relaxed = mode.model_copy(update={"lies": (1, max(mode.lies[1], lies))})
    problems = [f"{i.code}: {i.message}" for i in check_case(scenario.case, relaxed)]
    expected = {a.key for a in enumerate_actions(scenario.case)}
    given = set(scenario.responses)
    problems += [f"応答がありません: {key}" for key in sorted(expected - given)]
    problems += [f"使われない応答があります: {key}" for key in sorted(given - expected)]
    problems += [
        f"応答が空です: {key}" for key, text in scenario.responses.items() if not text.strip()
    ]
    return problems


def build_scripted_pack(scenario: ScriptedScenario, mode: TrialMode) -> OfflinePack:
    problems = validate_scenario(scenario, mode)
    if problems:
        raise ScriptedScenarioError("\n".join(problems))
    case = scenario.case
    responses = [
        OfflineResponse(
            key=action.key,
            witness_id=action.testimony.witness_id,
            text=scenario.responses[action.key].strip(),
            should_collapse=action.option.contradiction_id is not None,
            check=None,
            attempts=1,
        )
        for action in enumerate_actions(case)
    ]
    return OfflinePack(
        # 尋問の中で手に入る証拠品も含める(手元にあるかはブラウザが行動の列から決める)
        case=case.public_view({e.id for e in case.evidence}),
        theme=case.theme,
        answers=pack_answers(case),
        explanation=build_explanation(case),
        mode=pack_mode(mode),
        responses=responses,
        meta=OfflineMeta(
            # 台本は同じ入力から同じパックになるよう、生成日時に事件の作成日時を使う
            generated_at=case.created_at,
            models={},
            prompt_versions={},
            responses=len(responses),
            deviations=0,
            unchecked=0,
            source="scripted",
            tutorial=scenario.tutorial,
        ),
    )
