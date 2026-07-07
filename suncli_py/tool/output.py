"""工具执行结果模型。

对应 ``com.paicli.tool.ToolOutput``。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolOutput:
    """单个工具调用的执行结果。"""

    tool_name: str
    content: str  # 主要文本输出
    is_error: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def truncated(self, max_chars: int = 8_000) -> ToolOutput:
        """返回截断后的副本。"""
        if len(self.content) <= max_chars:
            return self
        return ToolOutput(
            tool_name=self.tool_name,
            content=self.content[:max_chars] + f"\n...(已截断，原 {len(self.content)} 字符)",
            is_error=self.is_error,
            metadata={**self.metadata, "truncated": True, "original_length": len(self.content)},
        )

    @classmethod
    def error(cls, tool_name: str, message: str) -> ToolOutput:
        """创建错误结果。"""
        return cls(tool_name=tool_name, content=message, is_error=True)


@dataclass
class ToolExecutionResult:
    """一批工具调用的聚合结果。"""

    outputs: list[ToolOutput]
    total_duration_ms: float = 0.0

    @property
    def all_success(self) -> bool:
        return all(not o.is_error for o in self.outputs)

    def format_for_llm(self) -> str:
        """格式化为 LLM 可理解的结果文本。"""
        parts: list[str] = []
        for output in self.outputs:
            status = "❌ 错误" if output.is_error else "✅ 成功"
            parts.append(f"[{status}] {output.tool_name}:\n{output.content}")
        return "\n\n".join(parts)
