"""技能上下文缓冲区 —— 与 Java 版格式完全一致。

对应 ``com.paicli.skill.SkillContextBuffer``。
"""

from __future__ import annotations


class SkillContextBuffer:
    """Agent 实例本地的技能上下文缓冲。"""

    MAX_SKILLS = 3

    def __init__(self) -> None:
        self._buffer: dict[str, str] = {}

    def push(self, name: str, body: str) -> None:
        """推送一个技能正文到缓冲区。同名替换并刷新到末尾。"""
        if name in self._buffer:
            del self._buffer[name]
        if len(self._buffer) >= self.MAX_SKILLS:
            oldest = next(iter(self._buffer))
            del self._buffer[oldest]
        self._buffer[name] = body

    def drain(self) -> str:
        """排空缓冲区，返回格式化的技能正文（与 Java 格式一致）。

        Returns:
            格式化的技能正文，空时返回空字符串 ""。
        """
        if not self._buffer:
            return ""

        parts: list[str] = []
        for name, body in self._buffer.items():
            parts.append(f"## 已加载 Skill：{name}\n{body}\n")

        self._buffer.clear()
        if not parts:
            return ""
        return "\n".join(parts) + "\n---"

    def clear(self) -> None:
        self._buffer.clear()

    def __len__(self) -> int:
        return len(self._buffer)
