"""モード定義(ルーブリック、矛盾タイプ、進行、勝利条件)。"""

from llm_court.modes.debate import DEBATE_MODE, DebateMode, RubricCriterion, Turn
from llm_court.modes.trial import TRIAL_MODE, TrialMode

__all__ = ["DEBATE_MODE", "TRIAL_MODE", "DebateMode", "RubricCriterion", "TrialMode", "Turn"]
