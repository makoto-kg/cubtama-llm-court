"""検索結果の重複除去(URL とタイトルの正規化)。"""

import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from llm_court.research.search import SearchHit

_TRACKING_PARAMS = {"fbclid", "gclid", "yclid", "mc_cid", "mc_eid", "ref", "ref_src", "spm"}
_TITLE_SUFFIX = re.compile(r"\s*[|｜\-–—:：]\s*[^|｜\-–—:：]{1,30}$")
_SPACES = re.compile(r"\s+")


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower().removeprefix("www.")
    if parts.port and parts.port not in (80, 443):
        host = f"{host}:{parts.port}"
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in _TRACKING_PARAMS
    ]
    path = parts.path.rstrip("/") or "/"
    scheme = "https" if parts.scheme in ("http", "https") else parts.scheme.lower()
    return urlunsplit((scheme, host, path, urlencode(sorted(query)), ""))


def normalize_title(title: str) -> str:
    """NFKC・空白の統一・末尾のサイト名(「 | サイト名」等)の除去・小文字化。"""
    title = unicodedata.normalize("NFKC", title).strip()
    stripped = _TITLE_SUFFIX.sub("", title)
    # サフィックス除去で短くなりすぎる場合は元のタイトルを使う
    if len(stripped) >= 8:
        title = stripped
    return _SPACES.sub(" ", title).lower()


def dedupe_hits(hits: list[SearchHit]) -> list[SearchHit]:
    """URL またはタイトルが先行の結果と一致するものを捨てる(順序は保つ)。"""
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    result: list[SearchHit] = []
    for hit in hits:
        url_key = normalize_url(hit.url)
        title_key = normalize_title(hit.title) if hit.title else ""
        if url_key in seen_urls or (title_key and title_key in seen_titles):
            continue
        seen_urls.add(url_key)
        if title_key:
            seen_titles.add(title_key)
        result.append(hit)
    return result
