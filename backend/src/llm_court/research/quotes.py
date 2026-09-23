"""引用(`KeyFact.quote`)が取得本文に実在するかの照合。"""

import re
import unicodedata

MIN_QUOTE_CHARS = 8
"""正規化後にこれより短い引用は、偶然の一致を避けるため検証済みにしない。"""

_ELLIPSIS = re.compile(r"(?:…+|\.{3,}|・{3,})")
_IGNORED = re.compile(r"[\s​‌‍⁠﻿]+")
_TRANSLATE = str.maketrans(
    {
        "“": '"',
        "”": '"',
        "„": '"',
        "‘": "'",
        "’": "'",
        "「": '"',
        "」": '"',
        "『": '"',
        "』": '"',
        "‐": "-",
        "‑": "-",
        "‒": "-",
        "–": "-",
        "—": "-",
        "―": "-",
        "−": "-",
    }
)


def normalize_for_match(text: str) -> str:
    """照合用に正規化する(NFKC、空白・ゼロ幅文字の除去、引用符・ダッシュの統一、小文字化)。"""
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(_TRANSLATE)
    text = _IGNORED.sub("", text)
    return text.lower()


def verify_quote(quote: str, source_text: str) -> bool:
    """`quote` が `source_text` に(正規化後に)含まれるか。

    省略記号(…)で区切られた引用は、各断片がこの順に出現すれば一致とみなす。
    """
    fragments = [normalize_for_match(f) for f in _ELLIPSIS.split(quote)]
    fragments = [f.strip("\"'") for f in fragments]
    fragments = [f for f in fragments if f]
    if not fragments or sum(len(f) for f in fragments) < MIN_QUOTE_CHARS:
        return False
    source = normalize_for_match(source_text)
    pos = 0
    for fragment in fragments:
        idx = source.find(fragment, pos)
        if idx < 0:
            return False
        pos = idx + len(fragment)
    return True
