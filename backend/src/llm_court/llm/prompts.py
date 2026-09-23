"""プロンプトテンプレート(Jinja2)の読み込み。

テンプレートは `prompts/<role>/<name>.j2`。`{% block system %}` と `{% block user %}` を
定義するとそれぞれ system / user メッセージになる。ブロックがなければ全体を user とする。
バージョンはテンプレートファイルの SHA-256(先頭 12 桁)。
"""

import hashlib
from pathlib import Path

import jinja2
from pydantic import BaseModel, ConfigDict

from llm_court.llm.backend import ChatMessage
from llm_court.llm.errors import PromptError


class RenderedPrompt(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    version: str
    system: str | None
    user: str

    def to_messages(self) -> list[ChatMessage]:
        messages: list[ChatMessage] = []
        if self.system:
            messages.append(ChatMessage(role="system", content=self.system))
        messages.append(ChatMessage(role="user", content=self.user))
        return messages


class PromptLoader:
    def __init__(self, prompts_dir: Path) -> None:
        self._dir = prompts_dir
        self._env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(prompts_dir),
            undefined=jinja2.StrictUndefined,
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=False,
        )

    def render(self, name: str, /, **variables: object) -> RenderedPrompt:
        """`<prompts_dir>/<name>.j2` をレンダリングする。"""
        try:
            template = self._env.get_template(f"{name}.j2")
            if template.filename is None:
                raise PromptError(f"テンプレート {name} のファイルが特定できません")
            version = hashlib.sha256(Path(template.filename).read_bytes()).hexdigest()[:12]
            if "user" in template.blocks:
                context = template.new_context(dict(variables))
                user = "".join(template.blocks["user"](context)).strip()
                system = (
                    "".join(template.blocks["system"](context)).strip()
                    if "system" in template.blocks
                    else None
                )
            else:
                user = template.render(**variables).strip()
                system = None
        except jinja2.TemplateNotFound as e:
            raise PromptError(f"テンプレート {name} が {self._dir} にありません") from e
        except jinja2.TemplateError as e:
            raise PromptError(f"テンプレート {name} のレンダリングに失敗しました: {e}") from e
        return RenderedPrompt(name=name, version=version, system=system or None, user=user)
