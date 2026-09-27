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

    # --- プレイ(Phase 9) ---
    penalty_gauge: int = 5
    """プレイヤーのペナルティゲージの初期値。0 以下で閉廷(解説へ進む)。"""
    penalties: dict[str, int] = {"strong": 0, "weak": 1, "trap": 2}
    """つきつけた組の強さごとの減少量(ゆさぶるは減点なし)。"""
    distractor_options: int = 2
    """1 回の尋問で並べる「はずれ」の組(行 × 証拠品)の数。"""
    probe_options: int = 2
    """1 回の尋問で並べる「ゆさぶる」の数。"""
    check_deviations: bool = True
    """証人の応答のたびに、台本からの逸脱を判定役に検査させるか。"""

    def penalty_for(self, strength: str | None) -> int:
        return self.penalties.get(strength or "", 0)


TRIAL_MODE = TrialMode()
