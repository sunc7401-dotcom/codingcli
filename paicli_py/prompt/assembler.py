"""提示词组装器 —— 分层组装 system prompt。

对应 ``com.paicli.prompt.PromptAssembler``。

组装层次: base → mode → approvals → personality → context
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from paicli_py.prompt.mode import PromptMode


class PromptAssembler:
    """分层组装 LLM 系统提示词。

    使用 Markdown 模板文件，按顺序拼接。
    """

    # 提示词模板路径（相对于包资源目录）
    PROMPTS_DIR = Path(__file__).parent.parent / "resources" / "prompts"

    # 默认提示词模板（内置，不依赖外部文件）
    DEFAULT_SYSTEM_PROMPT = """你是一个 AI 编程助手 PaiCLI，运行在终端中。
你可以使用工具来读取文件、搜索代码、执行命令等。

## 可用工具
你可以调用函数来完成任务。每次可以调用多个独立的函数。

## 规则
- 用中文回答用户
- 修改代码前先理解上下文
- 写出符合现有代码风格的代码
- 执行命令前确认安全性
"""

    def __init__(self, mode: PromptMode | None = None) -> None:
        self._mode = mode
        self._sections: list[str] = []

    def add_section(self, title: str, content: str) -> None:
        """添加一个提示词段。"""
        if content.strip():
            self._sections.append(f"## {title}\n\n{content}")

    def assemble(self, project_memory: str | None = None) -> str:
        """组装最终的 system prompt。

        顺序: 基础提示词 → 各段内容 → 项目记忆
        """
        parts: list[str] = [self.DEFAULT_SYSTEM_PROMPT]

        if self._sections:
            parts.extend(self._sections)

        if project_memory:
            parts.append(f"## 项目上下文\n\n{project_memory}")

        return "\n\n".join(parts)

    @classmethod
    def create_default(cls) -> PromptAssembler:
        """创建默认组配器。"""
        return cls()
