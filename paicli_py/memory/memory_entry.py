"""记忆条目 —— Memory 系统的基础数据单元。

对应 ``com.paicli.memory.MemoryEntry``。
"""

from __future__ import annotations

import math
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class MemoryType(Enum):
    """记忆类型。"""
    CONVERSATION = "CONVERSATION"  # 对话记忆
    FACT = "FACT"                  # 事实记忆（用户偏好、项目信息等）
    SUMMARY = "SUMMARY"            # 摘要记忆
    TOOL_RESULT = "TOOL_RESULT"    # 工具执行结果


@dataclass
class MemoryEntry:
    """记忆系统的基础数据单元。"""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    content: str = ""
    type: MemoryType = MemoryType.CONVERSATION
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, str] = field(default_factory=dict)
    token_count: int = 0

    # ── 静态工具方法 ──────────────────────────────────────

    @staticmethod
    def estimate_tokens(text: str | None) -> int:
        """粗略估算 token 数（中文约 1.5 字/token，英文约 4 字符/token）。"""
        if not text:
            return 0
        chinese_chars = sum(1 for c in text if '一' <= c <= '鿿')
        other_chars = len(text) - chinese_chars
        return math.ceil(chinese_chars / 1.5 + other_chars / 4.0)

    # ── scope 辅助属性（LongTermMemory 使用）───────────────

    @property
    def scope(self) -> str:
        return self.metadata.get("scope", "global")

    @scope.setter
    def scope(self, value: str) -> None:
        self.metadata["scope"] = value

    @property
    def project_key(self) -> str | None:
        return self.metadata.get("project_key")

    @project_key.setter
    def project_key(self, value: str) -> None:
        self.metadata["project_key"] = value

    def __repr__(self) -> str:
        preview = self.content[:80] + "..." if len(self.content) > 80 else self.content
        return f"[{self.type.value}] {self.id}: {preview}"
