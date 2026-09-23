"""環境変数・`.env` から読み込むアプリケーション設定。"""

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """アプリケーション全体の設定。環境変数は `LLM_COURT_` プレフィックスで上書きできる。"""

    model_config = SettingsConfigDict(
        env_prefix="LLM_COURT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    models_config_path: Path = Path("config/models.yaml")
    """役割・モデル・プロバイダの割り当てファイル。"""

    searxng_url: str = "http://localhost:8080"
    """セルフホストの SearXNG のベース URL。"""

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
