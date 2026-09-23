"""LLM 層の例外。"""


class LLMError(Exception):
    """LLM 呼び出しの失敗。"""


class LLMConnectionError(LLMError):
    """サーバーに接続できない、またはタイムアウトした。"""


class LLMRequestRejectedError(LLMError):
    """サーバーがリクエストを受け付けなかった(未対応のパラメータ等。HTTP 400 / 422)。"""

    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


class StructuredOutputError(LLMError):
    """構造化出力が再試行の上限までに検証を通らなかった。"""

    def __init__(self, message: str, attempts: list[str]) -> None:
        super().__init__(message)
        self.attempts = attempts
        """各試行の失敗理由。"""


class PromptError(Exception):
    """プロンプトテンプレートの読み込み・レンダリングに失敗した。"""
