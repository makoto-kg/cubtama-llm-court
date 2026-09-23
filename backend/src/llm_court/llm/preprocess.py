"""LLM 出力の前処理(思考部分・コードフェンスの除去、JSON の抽出)。"""

import json
import re
from typing import Any, cast

_THINK_OPEN = "<think>"
_THINK_CLOSE = "</think>"
_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL)
_FENCE = re.compile(r"```(?:json|JSON)?\s*\n?(.*?)```", re.DOTALL)


def strip_reasoning(text: str) -> str:
    """本文に混入した思考部分(`<think>…</think>`)を除去する。

    開きタグなしの `</think>` はそれ以前を思考部分とみなす(チャットテンプレートが開きタグを
    プロンプト側に入れるモデルがあるため)。閉じられていない `<think>` 以降は捨てる。
    """
    text = _THINK_BLOCK.sub("", text)
    if _THINK_CLOSE in text:
        text = text.rsplit(_THINK_CLOSE, 1)[1]
    if _THINK_OPEN in text:
        text = text.split(_THINK_OPEN, 1)[0]
    return text.strip()


def extract_json(text: str) -> dict[str, Any]:
    """テキストから最初の JSON オブジェクトを取り出してパースする。

    思考部分・コードフェンス・前後の説明文は無視する。見つからなければ `ValueError`。
    """
    text = strip_reasoning(text)
    candidates = [m.group(1) for m in _FENCE.finditer(text)] + [text]
    decoder = json.JSONDecoder()
    for candidate in candidates:
        for i, ch in enumerate(candidate):
            if ch != "{":
                continue
            try:
                value, _ = decoder.raw_decode(candidate, i)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return cast(dict[str, Any], value)
    raise ValueError("出力に JSON オブジェクトが見つかりません")


def _partial_tag_len(buf: str, tag: str) -> int:
    """`buf` の末尾が `tag` の先頭部分と一致する長さ。"""
    for n in range(min(len(buf), len(tag) - 1), 0, -1):
        if buf.endswith(tag[:n]):
            return n
    return 0


class ThinkFilter:
    """ストリーミング中のチャンクから `<think>…</think>` を取り除く。

    タグがチャンク境界をまたいでも正しく除去する。開きタグなしの `</think>` はタグだけを
    除去する(それ以前のテキストは既に送出済みのため)。
    """

    def __init__(self) -> None:
        self._buf = ""
        self._in_think = False

    def feed(self, chunk: str) -> str:
        self._buf += chunk
        out: list[str] = []
        while True:
            if self._in_think:
                idx = self._buf.find(_THINK_CLOSE)
                if idx < 0:
                    keep = _partial_tag_len(self._buf, _THINK_CLOSE)
                    self._buf = self._buf[len(self._buf) - keep :]
                    break
                self._buf = self._buf[idx + len(_THINK_CLOSE) :]
                self._in_think = False
                continue
            open_idx = self._buf.find(_THINK_OPEN)
            close_idx = self._buf.find(_THINK_CLOSE)
            hits = [
                (i, t) for i, t in ((open_idx, _THINK_OPEN), (close_idx, _THINK_CLOSE)) if i >= 0
            ]
            if hits:
                idx, tag = min(hits)
                out.append(self._buf[:idx])
                self._buf = self._buf[idx + len(tag) :]
                self._in_think = tag == _THINK_OPEN
                continue
            keep = max(
                _partial_tag_len(self._buf, _THINK_OPEN), _partial_tag_len(self._buf, _THINK_CLOSE)
            )
            out.append(self._buf[: len(self._buf) - keep])
            self._buf = self._buf[len(self._buf) - keep :]
            break
        return "".join(out)

    def flush(self) -> str:
        rest = "" if self._in_think else self._buf
        self._buf = ""
        return rest
