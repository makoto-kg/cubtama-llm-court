"""researcher の構造化出力スキーマ。"""

from pydantic import BaseModel, Field


class SearchQueries(BaseModel):
    queries: list[str] = Field(min_length=1, max_length=10, description="検索クエリ")


class KeyFactDraft(BaseModel):
    text: str = Field(description="事実の要約(1文)")
    quote: str = Field(description="本文からそのまま抜き書きした根拠の一節")


class EvidenceDraft(BaseModel):
    relevant: bool = Field(description="テーマの議論に役立つ情報を含むか")
    title: str = Field(description="証拠品の名前(簡潔に)")
    summary: str = Field(description="ページ内容のうちテーマに関係する部分の要約(2〜3文)")
    key_facts: list[KeyFactDraft] = Field(max_length=5, description="議論に使える事実")
