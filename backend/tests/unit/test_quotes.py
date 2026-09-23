import pytest

from llm_court.research.quotes import normalize_for_match, verify_quote

SOURCE = """ある国では２年間にわたり、無作為に選ばれた失業者2,000人に毎月一定額を支給した。
研究チームは「就労意欲が下がるという懸念は確認されなかった」と述べている。
財源の確保は今後の検討課題として
残った。"""


def test_normalize_unifies_width_spaces_and_quotes() -> None:
    assert normalize_for_match("ＡＢＣ　１２３") == "abc123"
    assert normalize_for_match("「引用」“quote”") == '"引用""quote"'
    assert normalize_for_match("a​b\nc") == "abc"
    assert normalize_for_match("2020–2021") == "2020-2021"


@pytest.mark.parametrize(
    "quote",
    [
        "無作為に選ばれた失業者2,000人に毎月一定額を支給した",
        "ある国では2年間にわたり",  # 全角数字と半角数字の違い
        "財源の確保は今後の検討課題として残った",  # 改行をまたぐ
        "「就労意欲が下がるという懸念は確認されなかった」",
        "研究チームは…懸念は確認されなかった",  # 省略記号
        "ある国では２年間にわたり...財源の確保は",
    ],
)
def test_verify_quote_accepts(quote: str) -> None:
    assert verify_quote(quote, SOURCE)


@pytest.mark.parametrize(
    "quote",
    [
        "無作為に選ばれた失業者3,000人に毎月一定額を支給した",  # 数字の改変
        "就労意欲は大きく下がった",  # 本文にない
        "財源の確保は…研究チームは",  # 省略記号の断片の順序が逆
        "失業者",  # 短すぎる
        "",
        "……",
    ],
)
def test_verify_quote_rejects(quote: str) -> None:
    assert not verify_quote(quote, SOURCE)
