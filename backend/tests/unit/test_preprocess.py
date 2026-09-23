import pytest

from llm_court.llm.preprocess import ThinkFilter, extract_json, strip_reasoning


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("<think>考え中</think>\n答え", "答え"),
        ("前<think>a</think>中<think>b</think>後", "前中後"),
        ("思考だけが先に来る</think>本文", "本文"),  # 開きタグがプロンプト側にあるモデル
        ("本文<think>打ち切られた思考", "本文"),
        ("思考なし", "思考なし"),
    ],
)
def test_strip_reasoning(raw: str, expected: str) -> None:
    assert strip_reasoning(raw) == expected


def test_extract_json_plain() -> None:
    assert extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_from_fence_and_prose() -> None:
    raw = 'はい、回答です。\n```json\n{"a": {"b": [1, 2]}}\n```\n以上です。'
    assert extract_json(raw) == {"a": {"b": [1, 2]}}


def test_extract_json_skips_think_and_braces_in_prose() -> None:
    raw = '<think>{"wrong": true}</think>集合 {x} ではなく {"a": "}"} です'
    assert extract_json(raw) == {"a": "}"}


def test_extract_json_not_found() -> None:
    with pytest.raises(ValueError, match="JSON"):
        extract_json("JSON はありません")


def _run_filter(chunks: list[str]) -> str:
    f = ThinkFilter()
    return "".join(f.feed(c) for c in chunks) + f.flush()


def test_think_filter_across_chunk_boundaries() -> None:
    chunks = ["前", "<th", "ink>考", "え</thi", "nk>後", "ろ"]
    assert _run_filter(chunks) == "前後ろ"


def test_think_filter_single_char_chunks() -> None:
    text = "A<think>xyz</think>B<think>q</think>C"
    assert _run_filter(list(text)) == "ABC"


def test_think_filter_keeps_lookalike_text() -> None:
    assert _run_filter(["a <thin", "g> b"]) == "a <thing> b"


def test_think_filter_drops_unclosed_think() -> None:
    assert _run_filter(["本文<think>未完"]) == "本文"


def test_think_filter_removes_stray_close_tag() -> None:
    assert _run_filter(["思考", "</think>本文"]) == "思考本文"
