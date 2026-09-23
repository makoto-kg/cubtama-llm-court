"""SearXNG の JSON API による検索。"""

from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict


class SearchError(Exception):
    """検索サーバーに接続できない、または応答が不正。"""


class SearchHit(BaseModel):
    model_config = ConfigDict(frozen=True)

    url: str
    title: str
    snippet: str = ""
    engine: str | None = None
    query: str = ""


class SearXNGClient:
    def __init__(self, base_url: str, *, timeout_s: float, client: httpx.AsyncClient) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s
        self._client = client

    async def search(self, query: str, *, limit: int, language: str = "ja") -> list[SearchHit]:
        try:
            response = await self._client.get(
                f"{self._base_url}/search",
                params={"q": query, "format": "json", "language": language},
                timeout=self._timeout_s,
            )
            response.raise_for_status()
            data: dict[str, Any] = response.json()
        except (httpx.HTTPError, ValueError) as e:
            raise SearchError(f"SearXNG での検索に失敗しました({query}): {e}") from e
        hits: list[SearchHit] = []
        for item in data.get("results", []):
            url = item.get("url")
            if not isinstance(url, str) or not url.startswith(("http://", "https://")):
                continue
            hits.append(
                SearchHit(
                    url=url,
                    title=str(item.get("title") or ""),
                    snippet=str(item.get("content") or ""),
                    engine=item.get("engine"),
                    query=query,
                )
            )
            if len(hits) >= limit:
                break
        return hits
