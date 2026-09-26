from pathlib import Path

import pytest
import yaml

from llm_court.eval.spec import EvalSpec, EvalSpecError, load_spec

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "spec.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_example_spec_is_valid() -> None:
    # 同梱のサンプルは手元の *.local.yaml を参照するため、内容の検証だけを行う
    raw = yaml.safe_load((BACKEND_ROOT / "eval/specs/example.yaml").read_text(encoding="utf-8"))
    spec = EvalSpec.model_validate(raw)
    assert [c.name for c in spec.configs] == ["gpt-oss-20b", "gemma-4-12b"]
    for topic in spec.topics:
        assert (BACKEND_ROOT / topic.evidence).exists()


def test_load_spec_defaults(tmp_path: Path) -> None:
    (tmp_path / "m.yaml").write_text("x", encoding="utf-8")
    (tmp_path / "e.json").write_text("{}", encoding="utf-8")
    spec = load_spec(
        _write(
            tmp_path,
            f"""
name: テスト
configs:
  - {{name: a, models: {tmp_path / "m.yaml"}}}
topics:
  - {{topic: 論題, evidence: {tmp_path / "e.json"}}}
""",
        )
    )
    assert (spec.rounds, spec.runs, spec.judge_repeats) == (1, 1, 2)
    assert spec.reference_judge is None


def test_missing_files(tmp_path: Path) -> None:
    body = """
name: テスト
configs: [{name: a, models: nope.yaml}]
topics: [{topic: 論題, evidence: nope.json}]
"""
    with pytest.raises(EvalSpecError, match=r"nope\.yaml.*nope\.json"):
        load_spec(_write(tmp_path, body))


@pytest.mark.parametrize(
    "body",
    [
        "name: x\nconfigs: []\ntopics: [{topic: t, evidence: e}]",
        "name: x\nconfigs: [{name: a, models: m}, {name: a, models: m}]\n"
        "topics: [{topic: t, evidence: e}]",
        "name: x\nconfigs: [{name: a, models: m}]\ntopics: [{topic: t}]",
        "name: x\nrounds: 0\nconfigs: [{name: a, models: m}]\ntopics: [{topic: t, evidence: e}]",
        "name: x\nunknown: 1\nconfigs: [{name: a, models: m}]\ntopics: [{topic: t, evidence: e}]",
        ": [",
    ],
)
def test_invalid_spec(tmp_path: Path, body: str) -> None:
    with pytest.raises(EvalSpecError):
        load_spec(_write(tmp_path, body))
