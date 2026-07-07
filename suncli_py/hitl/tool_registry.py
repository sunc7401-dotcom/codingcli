"""HITL 工具注册表 —— 在 ToolRegistry 基础上注入人机协同审批。

对应 ``com.paicli.hitl.HitlToolRegistry``。

核心流程：
1. 工具被调用 → 判断是否需要审批
2. 需要审批 → 展示审批请求 → 等待用户决策
3. 批准 → 执行工具；拒绝 → 返回错误
"""

from __future__ import annotations

import json
from typing import Any

from suncli_py.hitl.handler import ApprovalDecision, ApprovalPolicy, ApprovalRequest, HitlHandler
from suncli_py.tool.registry import ToolRegistry


class HitlToolRegistry(ToolRegistry):
    """带 HITL 审批的工具注册表。

    继承 ToolRegistry，在执行危险工具前注入审批流程。
    """

    def __init__(self, hitl_handler: HitlHandler) -> None:
        super().__init__()
        self._hitl_handler = hitl_handler

    @property
    def hitl_handler(self) -> HitlHandler:
        return self._hitl_handler

    async def _execute_single(self, tool_call: Any):
        """重写：在工具执行前插入 HITL 审批检查。"""

        # 获取工具名和参数
        if hasattr(tool_call, "name"):
            tool_name = tool_call.name
            _tool_id = tool_call.id  # reserved for future use
            args_str = tool_call.arguments
        else:
            tool_name = tool_call.get("function", {}).get("name", "")
            _tool_id = tool_call.get("id", "")
            args_str = tool_call.get("function", {}).get("arguments", "{}")

        # 不需要审批或 HITL 禁用 → 直接执行
        if not ApprovalPolicy.requires_approval(tool_name) or not self._hitl_handler.enabled:
            return await self._do_execute(tool_name, args_str)

        # 检查智能体打开的标签（浏览器场景）
        # 此处检查"始终批准"状态
        server_name = ApprovalPolicy.mcp_server_name(tool_name) if tool_name.startswith("mcp__") else None
        if hasattr(self._hitl_handler, "is_approved_all_by_tool"):
            if self._hitl_handler.is_approved_all_by_tool(tool_name):
                return await self._do_execute(tool_name, args_str)
        if server_name and hasattr(self._hitl_handler, "is_approved_all_by_server"):
            if self._hitl_handler.is_approved_all_by_server(server_name):
                return await self._do_execute(tool_name, args_str)

        # 需要显式审批
        return await self._execute_after_approval(tool_name, args_str)

    async def _execute_after_approval(self, tool_name: str, args_str: str):
        """发起审批请求，根据决策执行或拒绝。"""
        from suncli_py.tool.output import ToolOutput

        # 构建审批请求
        try:
            params = json.loads(args_str) if isinstance(args_str, str) else args_str
        except json.JSONDecodeError:
            params = {}

        request = ApprovalRequest(
            tool_name=tool_name,
            tool_description=tool_name,
            params_summary=json.dumps(params, ensure_ascii=False)[:200],
            reason=ApprovalPolicy.get_reason(tool_name),
        )

        # 获取决策
        result = await self._hitl_handler.request_approval(request)

        if result.decision == ApprovalDecision.DENY:
            return ToolOutput(
                tool_name=tool_name,
                content=f"[HITL] 操作被拒绝: {result.reason or '用户拒绝'}",
                is_error=True,
            )

        if result.decision == ApprovalDecision.ALWAYS_APPROVE:
            # 记录"始终批准"
            if hasattr(self._hitl_handler, "_approved_all_by_tool"):
                self._hitl_handler._approved_all_by_tool.add(tool_name)

        # 批准 → 执行
        return await self._do_execute(tool_name, args_str)

    async def _do_execute(self, tool_name: str, args_str: str):
        """实际执行工具（绕过 HITL 检查，调用父类逻辑）。"""
        # 直接调用 ToolRegistry 的工具执行
        tool = self.get(tool_name)
        if tool is None:
            from suncli_py.tool.output import ToolOutput
            return ToolOutput(tool_name=tool_name, content=f"未知工具: {tool_name}", is_error=True)

        try:
            params = json.loads(args_str) if isinstance(args_str, str) else args_str
        except json.JSONDecodeError:
            from suncli_py.tool.output import ToolOutput
            return ToolOutput(tool_name=tool_name, content="参数解析失败", is_error=True)

        try:
            content = await tool.executor(params)
            from suncli_py.tool.output import ToolOutput
            return ToolOutput(tool_name=tool_name, content=content)
        except Exception as e:
            from suncli_py.tool.output import ToolOutput
            return ToolOutput(tool_name=tool_name, content=f"执行异常: {e}", is_error=True)
