"""取得・抽出済みページのローカルキャッシュ。"""

import hashlib
import logging
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

logger = logging.getLogger(__name__)


class FetchedPage(BaseModel):
    model_config = ConfigDict(frozen=True)

    url: str
    title: str | None
    text: str
    published_date: str | None
    fetched_at: datetime


class PageCache:
    def __init__(self, cache_dir: Path) -> None:
        self._dir = cache_dir / "pages"

    def _path(self, url: str) -> Path:
        return self._dir / f"{hashlib.sha256(url.encode()).hexdigest()}.json"

    def get(self, url: str) -> FetchedPage | None:
        path = self._path(url)
        if not path.exists():
            return None
        try:
            return FetchedPage.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValidationError) as e:
            logger.warning("キャッシュを読めないため再取得します: %s (%s)", url, e)
            return None

    def put(self, page: FetchedPage) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path(page.url).write_text(page.model_dump_json(), encoding="utf-8")
