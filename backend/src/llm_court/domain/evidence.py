"""証拠品(捜査で集めた情報源)のモデル。"""

import re
import unicodedata
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class KeyFact(BaseModel):
    """証拠品から取り出した事実。`quote` は取得本文からの抜き書き。"""

    model_config = ConfigDict(frozen=True)

    text: str
    quote: str
    quote_verified: bool
    """`quote` が取得本文に実在することを照合で確認できたか。"""


class Evidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    title: str
    source_url: str
    retrieved_at: datetime
    published_date: str | None = None
    """ページから抽出できた公開日(YYYY-MM-DD)。不明なら None。"""
    summary: str
    key_facts: list[KeyFact]

    @property
    def verified_facts(self) -> list[KeyFact]:
        return [f for f in self.key_facts if f.quote_verified]


class SkippedSource(BaseModel):
    """証拠品にしなかった情報源と理由。"""

    model_config = ConfigDict(frozen=True)

    url: str
    reason: str


class ResearchReport(BaseModel):
    """1 回の捜査の結果。JSON 保存の単位。"""

    model_config = ConfigDict(frozen=True)

    topic: str
    created_at: datetime
    queries: list[str]
    evidence: list[Evidence]
    skipped: list[SkippedSource]


# --- 証拠品 ID の表記ゆれ ---

# 括弧の有無・種類を問わず証拠品 ID とみなす(モデルは [EV-01] 以外の書き方もする)
_EVIDENCE_ID = re.compile(r"(?<![A-Za-z])EV\s*-\s*(\d+)", re.IGNORECASE)
# NFKC で ASCII にならないハイフン・ダッシュ類(gpt-oss は U+2011 を使う)
_DASHES = str.maketrans(dict.fromkeys("\u2010\u2011\u2012\u2013\u2014\u2015\u2212", "-"))


def normalize_citation_text(text: str) -> str:
    """NFKC とダッシュ類の統一。文字数は変わらない(位置の対応を保つ)。"""
    return unicodedata.normalize("NFKC", text).translate(_DASHES)


def find_evidence_ids(text: str) -> list[str]:
    """テキスト中の証拠品 ID を `EV-01` 形式にそろえ、出現順(重複なし)で返す。"""
    ids = [f"EV-{int(n):02d}" for n in _EVIDENCE_ID.findall(normalize_citation_text(text))]
    return list(dict.fromkeys(ids))


def normalize_evidence_ids(ids: list[str]) -> list[str]:
    """`ev-1`・`EV-01` 等の表記ゆれを `EV-01` 形式にそろえる(ID でないものは捨てる)。"""
    return find_evidence_ids(" ".join(ids))
