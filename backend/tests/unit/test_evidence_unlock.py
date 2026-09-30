"""尋問の中で手に入る証拠品(ADR 0019)。チュートリアルの事件で確かめる。"""

from pathlib import Path

from llm_court.agents.trial_analyst import TrialAnalyst
from llm_court.domain import Case, EvidenceUnlock
from llm_court.modes import TRIAL_MODE
from llm_court.offline.scripted import build_scripted_pack, load_scenario
from llm_court.offline.simulate import enumerate_actions
from llm_court.scenario.checks import check_case

TUTORIAL = Path(__file__).resolve().parents[2] / "scenarios" / "tutorial-churu.yaml"
TRIGGER = ("probe", "TS-02-3", None)


def tutorial() -> Case:
    return load_scenario(TUTORIAL).case


def test_locked_evidence_is_hidden_until_the_action() -> None:
    case = tutorial()
    assert case.locked_evidence_ids == {"CE-06"}
    assert "CE-06" not in case.available_evidence_ids(())
    assert "CE-06" not in {e.id for e in case.public_view().evidence}
    assert "CE-06" in case.available_evidence_ids({TRIGGER})
    assert "CE-06" in {
        e.id for e in case.public_view(case.available_evidence_ids({TRIGGER})).evidence
    }


def test_analyst_offers_only_evidence_in_hand_and_always_the_unlocking_probe() -> None:
    case = tutorial()
    analyst = TrialAnalyst(TRIAL_MODE)
    testimony = case.testimonies[1]
    solved = {"X-01", "X-02"}
    for seed in ("a", "b", "c"):
        options = analyst.prepare(
            case=case, testimony=testimony, solved=solved, tried=set(), id_prefix="Q", seed=seed
        )
        assert all(o.evidence_id != "CE-06" for o in options)
        assert any(o.kind == "probe" and o.line_id == "TS-02-3" for o in options)
        # 正解の証拠品が手元にない矛盾(X-04)は、まだ正解の組を並べない
        assert all(o.contradiction_id != "X-04" for o in options)

    options = analyst.prepare(
        case=case, testimony=testimony, solved=solved, tried={TRIGGER}, id_prefix="Q", seed="a"
    )
    assert any(o.contradiction_id == "X-04" and o.evidence_id == "CE-06" for o in options)


def test_enumerate_actions_skips_evidence_not_yet_reachable() -> None:
    keys = {a.key for a in enumerate_actions(tutorial())}
    assert "present:TS-01-1:CE-06" not in keys
    assert "present:TS-02-2:CE-06" in keys
    assert len(keys) == 3 * 6 + 3 * 7


def test_pack_carries_all_evidence_and_unlocks() -> None:
    pack = build_scripted_pack(load_scenario(TUTORIAL), TRIAL_MODE)
    assert "CE-06" in {e.id for e in pack.case.evidence}
    assert pack.answers.unlocks == [EvidenceUnlock(evidence_id="CE-06", line_id="TS-02-3")]


def test_check_case_rejects_unlocks_that_come_too_late_or_point_nowhere() -> None:
    case = tutorial()
    assert check_case(case, TRIAL_MODE.model_copy(update={"lies": (1, 4)})) == []

    def codes(unlocks: list[EvidenceUnlock]) -> set[str]:
        changed = case.model_copy(update={"evidence_unlocks": unlocks})
        return {i.code for i in check_case(changed, TRIAL_MODE.model_copy(update={"lies": (1, 4)}))}

    # 証言 1 の矛盾に使う証拠品を、証言 2 で手に入れる
    late = EvidenceUnlock(evidence_id="CE-04", line_id="TS-02-3")
    assert "unreachable_unlock" in codes([*case.evidence_unlocks, late])
    assert "missing_line" in codes([EvidenceUnlock(evidence_id="CE-06", line_id="TS-09-1")])
    bad_present = EvidenceUnlock(
        evidence_id="CE-06", kind="present", line_id="TS-02-3", presented_evidence_id="CE-06"
    )
    assert "unlock_reference" in codes([bad_present])


def test_prosecutor_is_a_known_person_other_than_the_defendant() -> None:
    case = tutorial()
    assert case.prosecutor_id == "P-02"
    assert case.public_view().prosecutor_id == "P-02"
    mode = TRIAL_MODE.model_copy(update={"lies": (1, 4)})
    for bad in ("P-09", case.defendant_id):
        changed = case.model_copy(update={"prosecutor_id": bad})
        assert "prosecutor_reference" in {i.code for i in check_case(changed, mode)}
