"""環境変数・`.env` から読み込むアプリケーション設定。"""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ResearchSettings(BaseModel):
    """捜査パイプライン(検索・本文取得・証拠品化)の設定。"""

    user_agent: str = "llm-court-research/0.1 (+local research bot)"
    query_count: int = Field(default=4, ge=1, le=10)
    """researcher に生成させる検索クエリ数。"""
    search_results_per_query: int = Field(default=8, ge=1)
    max_pages: int = Field(default=14, ge=1)
    """本文を取得して証拠品化を試みるページの上限。"""
    target_evidence: int = Field(default=8, ge=1)
    """集める証拠品の上限。"""
    fetch_timeout_s: float = Field(default=15.0, gt=0)
    fetch_max_bytes: int = Field(default=3_000_000, gt=0)
    fetch_concurrency: int = Field(default=4, ge=1)
    min_text_chars: int = Field(default=400, ge=0)
    """抽出本文がこれより短いページは捨てる。"""
    max_chars_per_page: int = Field(default=6000, ge=500)
    """researcher に渡すページ本文の最大文字数。使うモデルのコンテキスト長に合わせて調整する
    (日本語はおおむね 1 字 ≒ 1 トークン。8k コンテキストなら 3500 程度まで)。"""
    cache_dir: Path = Path(".cache")
    output_dir: Path = Path("data/research")


class ScenarioSettings(BaseModel):
    """裁判型の事件生成の設定。"""

    case_dir: Path = Path("data/cases")
    """生成した事件(JSON)の保存先。"""
    max_regenerations: int = Field(default=3, ge=0)
    """整合性チェックや solver 検証に失敗したときに作り直す上限回数。"""
    draft_retries: int = Field(default=2, ge=0)
    """各段階の出力の参照が不正なとき、問題点を伝えて作り直す上限回数。"""
    solver_runs: int = Field(default=3, ge=1)
    """solver に解かせる回数。solver の結果は揺れるため複数回解かせ、解答率で判定する。"""
    min_solve_rate: float = Field(default=0.6, ge=0.0, le=1.0)
    """「解ける」とみなす解答率(解けた回 ÷ 試行回数)の下限。"""


class Settings(BaseSettings):
    """アプリケーション全体の設定。環境変数は `LLM_COURT_` プレフィックスで上書きできる。"""

    model_config = SettingsConfigDict(
        env_prefix="LLM_COURT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_nested_delimiter="__",
    )

    models_config_path: Path = Path("config/models.yaml")
    """役割・モデル・プロバイダの割り当てファイル。"""

    prompts_dir: Path = Path("prompts")
    """プロンプトテンプレート(Jinja2)のディレクトリ。"""

    llm_structured_max_retries: int = Field(default=2, ge=0)
    """構造化出力の検証失敗時に再試行する上限回数。"""

    llm_record_io: bool = True
    """LLM 呼び出しの入出力(メッセージ・生出力・思考部分・パース結果)を記録する(思考ログ用)。"""

    llm_record_reasoning_max_chars: int = Field(default=4000, ge=0)
    """記録する思考部分の最大文字数。"""

    searxng_url: str = "http://localhost:8080"
    """セルフホストの SearXNG のベース URL。"""

    database_path: Path = Path("data/llm_court.db")
    """イベントストア(SQLite)のファイル。"""

    debate_output_dir: Path = Path("data/debates")
    """ディベートのイベントログ(JSONL)と法廷記録(Markdown)の保存先。"""

    sample_evidence_dir: Path = Path("eval/evidence")
    """API で選べる同梱の捜査結果(`llm-court research` の JSON)のディレクトリ。"""

    eval_output_dir: Path = Path("data/eval")
    """評価ハーネスの結果(CSV・Markdown・ディベートのログ)の保存先。"""

    api_cors_origins: list[str] = ["http://localhost:3000"]
    """API の CORS で許可するオリジン(フロントエンドの開発サーバー)。"""

    api_sse_keepalive_s: float = Field(default=15.0, gt=0)
    """SSE でイベントがないときにキープアライブを送る間隔。"""

    research: ResearchSettings = ResearchSettings()
    scenario: ScenarioSettings = ScenarioSettings()
    """環境変数では `LLM_COURT_RESEARCH__TARGET_EVIDENCE=6` のように指定する。"""

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
