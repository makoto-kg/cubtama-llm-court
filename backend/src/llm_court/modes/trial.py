"""裁判型のモード定義(事件の規模、罠の数、公開情報の制約)。"""

from pydantic import BaseModel, ConfigDict


class TrialMode(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str = "trial"
    learning_points: tuple[int, int] = (2, 3)
    """学習ポイントの数(最小, 最大)。"""
    people: tuple[int, int] = (3, 5)
    timeline_events: tuple[int, int] = (5, 12)
    lies: tuple[int, int] = (2, 3)
    """仕込む嘘(= 解くべき矛盾)の数。"""
    evidence: tuple[int, int] = (4, 8)
    traps_per_contradiction: int = 2
    question_options: tuple[int, int] = (3, 4)
    public_id_pattern: str = r"\b(?:LP|L|X|T)-\d+"
    """公開する文に含まれてはいけない非公開 ID の形(漏れのチェック)。"""


TRIAL_MODE = TrialMode()
