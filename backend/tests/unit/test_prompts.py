from pathlib import Path

import pytest

from llm_court.llm import PromptError, PromptLoader


def test_render_blocks(prompts: PromptLoader) -> None:
    rendered = prompts.render("bench/free", topic="テスト論題", stance="賛成")
    assert rendered.name == "bench/free"
    assert rendered.system is not None and "論者" in rendered.system
    assert "テスト論題" in rendered.user
    assert len(rendered.version) == 12
    messages = rendered.to_messages()
    assert [m.role for m in messages] == ["system", "user"]


def test_render_without_blocks(prompts: PromptLoader) -> None:
    rendered = prompts.render("llm/structured_feedback", error="理由")
    assert rendered.system is None
    assert rendered.user.startswith("直前の出力")
    assert "{#" not in rendered.user


def test_undefined_variable_is_error(prompts: PromptLoader) -> None:
    with pytest.raises(PromptError):
        prompts.render("bench/free", topic="論題のみ")


def test_missing_template_is_error(prompts: PromptLoader) -> None:
    with pytest.raises(PromptError, match="nope"):
        prompts.render("nope/missing")


def test_version_changes_with_file(tmp_path: Path) -> None:
    template = tmp_path / "t.j2"
    template.write_text("こんにちは {{ name }}", encoding="utf-8")
    loader = PromptLoader(tmp_path)
    v1 = loader.render("t", name="A").version
    template.write_text("こんばんは {{ name }}", encoding="utf-8")
    v2 = PromptLoader(tmp_path).render("t", name="A").version
    assert v1 != v2
