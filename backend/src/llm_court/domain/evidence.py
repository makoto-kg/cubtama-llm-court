"""証拠品(捜査で集めた情報源)のモデル。"""

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
