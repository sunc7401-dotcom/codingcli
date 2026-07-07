"""提示词上下文 —— 组装 system prompt 所需的所有上下文字段。

对应 ``com.paicli.prompt.PromptContext``。
使用 Builder 模式构建。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PromptContext:
    """组装 system prompt 所需的聚合上下文。

    使用 Builder 模式构建::

        ctx = (PromptContext.builder()
               .project_memory_context(pai_md)
               .memory_context(mem)
               .skill_index(idx)
               .build())
    """

    approval_mode: str = "suggest"
    project_memory_context: str = ""
    memory_context: str = ""
    external_context: str = ""
    skill_index: str = ""
    tools_enabled: bool = True
    variables: dict[str, str] = field(default_factory=dict)

    def variable(self, key: str) -> str:
        """查找变量值。"""
        return self.variables.get(key, "")

    @classmethod
    def empty(cls) -> PromptContext:
        """创建空的上下文。"""
        return cls()

    @classmethod
    def builder(cls) -> PromptContextBuilder:
        return PromptContextBuilder()


class PromptContextBuilder:
    """PromptContext 的 Builder。"""

    def __init__(self) -> None:
        self._ctx = PromptContext()

    def approval_mode(self, mode: str) -> PromptContextBuilder:
        self._ctx.approval_mode = mode
        return self

    def project_memory_context(self, text: str | None) -> PromptContextBuilder:
        if text:
            self._ctx.project_memory_context = text
        return self

    def memory_context(self, text: str | None) -> PromptContextBuilder:
        if text:
            self._ctx.memory_context = text
        return self

    def external_context(self, text: str | None) -> PromptContextBuilder:
        if text:
            self._ctx.external_context = text
        return self

    def skill_index(self, text: str | None) -> PromptContextBuilder:
        if text:
            self._ctx.skill_index = text
        return self

    def tools_enabled(self, enabled: bool) -> PromptContextBuilder:
        self._ctx.tools_enabled = enabled
        return self

    def variable(self, key: str, value: str) -> PromptContextBuilder:
        self._ctx.variables[key] = value
        return self

    def build(self) -> PromptContext:
        return self._ctx
