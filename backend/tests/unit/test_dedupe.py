import pytest

from llm_court.research.dedupe import dedupe_hits, normalize_title, normalize_url
from llm_court.research.search import SearchHit


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("https://www.Example.com/a/", "https://example.com/a"),
        ("http://example.com/a#section", "https://example.com/a"),
        ("https://example.com/a?utm_source=x&id=3&fbclid=y", "https://example.com/a?id=3"),
        ("https://example.com/a?b=2&a=1", "https://example.com/a?a=1&b=2"),
    ],
)
def test_normalize_url_equivalent(a: str, b: str) -> None:
    assert normalize_url(a) == normalize_url(b)


def test_normalize_url_keeps_meaningful_query() -> None:
    assert normalize_url("https://example.com/a?id=1") != normalize_url(
        "https://example.com/a?id=2"
    )


def test_normalize_title_strips_site_suffix() -> None:
    assert normalize_title("ベーシックインカムの課題 | 経済新聞") == normalize_title(
        "ベーシックインカムの課題 - 別サイト"
    )
    # 短すぎるタイトルはサフィックス除去しない
    assert normalize_title("BI | 経済新聞") != normalize_title("BI | 別サイト")


def test_dedupe_hits_by_url_and_title() -> None:
    hits = [
        SearchHit(url="https://a.example/1", title="ベーシックインカムの課題 | サイトA"),
        SearchHit(url="https://www.a.example/1/?utm_medium=x", title="別タイトル"),
        SearchHit(url="https://b.example/2", title="ベーシックインカムの課題 | サイトB"),
        SearchHit(url="https://c.example/3", title="記事C の見出しです"),
    ]
    result = dedupe_hits(hits)
    assert [h.url for h in result] == ["https://a.example/1", "https://c.example/3"]
