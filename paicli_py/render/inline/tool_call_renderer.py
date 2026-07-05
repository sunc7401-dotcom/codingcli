"""工具调用渲染器 —— 将 LLM 工具调用格式化为可折叠块。

对应 ``com.paicli.render.inline.ToolCallRenderer``。

核心设计：
- 按工具名分组
- 折叠标题显示工具名 + 数量
- 展开后显示每个调用的关键参数
"""

from __future__ import annotations

import json
from collections import OrderedDict
from typing import Any

from paicli_py.render.inline.block_registry import BlockRegistry
from paicli_py.render.inline.foldable_block import FoldableBlock

# ── 工具标签映射 ──────────────────────────────────────────

_TOOL_LABELS: dict[str, str] = {
    "read_file": "📖 读取文件",
    "write_file": "📝 写入文件",
    "list_dir": "📂 列出目录",
    "glob_files": "🔍 查找文件",
    "grep_code": "🔎 搜索代码",
    "execute_command": "⚡ 执行命令",
    "web_search": "🌐 搜索网页",
    "web_fetch": "📥 抓取网页",
    "search_code": "🧠 语义搜索",
    "load_skill": "📋 加载技能",
    "save_memory": "💾 保存记忆",
    "revert_turn": "↩️ 回滚变更",
    "create_project": "🏗️ 创建项目",
}

# ── 每个工具的关键参数 ────────────────────────────────────

_KEY_PARAMS: dict[str, str] = {
    "read_file": "path",
    "write_file": "path",
    "list_dir": "path",
    "glob_files": "pattern",
    "grep_code": "pattern",
    "execute_command": "command",
    "web_search": "query",
    "web_fetch": "url",
    "search_code": "query",
    "save_memory": "fact",
}


class ToolCallRenderer:
    """工具调用渲染器。"""

    def __init__(self, block_registry: BlockRegistry) -> None:
        self._registry = block_registry

    def render(self, tool_calls: list[Any]) -> None:
        """将工具调用列表渲染为可折叠块。"""
        if not tool_calls:
            return

        # 按工具名分组
        groups: OrderedDict[str, list[Any]] = OrderedDict()
        for tc in tool_calls:
            name = tc.name if hasattr(tc, "name") else tc.get("function", {}).get("name", "unknown")
            groups.setdefault(name, []).append(tc)

        # 生成标题和展开行
        header = self._collapsed_header(groups)
        lines = self._expanded_lines(groups)

        block = FoldableBlock(
            collapsed_header=header,
            expanded_lines=lines,
            collapse_footer="收起 (ctrl+o)",
        )
        self._registry.register(block)
        block.render_initial()

    # ── 内部 ────────────────────────────────────────────────

    @staticmethod
    def _collapsed_header(groups: OrderedDict[str, list[Any]]) -> str:
        """生成折叠标题。"""
        total_calls = sum(len(calls) for calls in groups.values())

        if len(groups) == 1:
            name, calls = next(iter(groups.items()))
            label = _TOOL_LABELS.get(name, f"🔧 {name}")
            if len(calls) > 1:
                return f"{label} × {len(calls)} (ctrl+o 展开)"
            else:
                key_param = ToolCallRenderer._extract_key_param(name, calls[0])
                return f"{label} {key_param} (ctrl+o 展开)"

        return f"🔧 {len(groups)} 组 / {total_calls} 个工具调用 (ctrl+o 展开)"

    @staticmethod
    def _expanded_lines(groups: OrderedDict[str, list[Any]]) -> list[str]:
        """生成展开后的行列表。"""
        lines: list[str] = []

        for name, calls in groups.items():
            label = _TOOL_LABELS.get(name, f"🔧 {name}")
            if name.startswith("mcp__"):
                # MCP 工具: mcp__server__tool
                parts = name.split("__", 2)
                label = f"🔌 {parts[1]}.{parts[2]}" if len(parts) >= 3 else f"🔌 {name}"

            lines.append(label)
            for tc in calls:
                key_param = ToolCallRenderer._extract_key_param(name, tc)
                lines.append(f"    {key_param}")
            lines.append("")

        return lines

    @staticmethod
    def _extract_key_param(tool_name: str, tool_call: Any) -> str:
        """提取工具调用的关键参数值。"""
        # 获取参数
        if hasattr(tool_call, "arguments"):
            args_str = tool_call.arguments
        elif hasattr(tool_call, "function") and hasattr(tool_call.function, "arguments"):
            args_str = tool_call.function.arguments
        else:
            args_str = tool_call.get("function", {}).get("arguments", "{}")

        try:
            args = json.loads(args_str) if isinstance(args_str, str) else args_str
        except (json.JSONDecodeError, TypeError):
            return str(args_str)[:80]

        # 查找关键参数
        key_param = _KEY_PARAMS.get(tool_name, "")
        if key_param and key_param in args:
            value = str(args[key_param])
            if len(value) > 80:
                return value[:77] + "..."
            return value

        # 降级：返回第一个参数值
        if args:
            first_val = str(next(iter(args.values())))
            return first_val[:80]

        return "(无参数)"
