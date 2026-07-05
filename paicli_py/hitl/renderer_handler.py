"""渲染器驱动的 HITL 处理器 —— 对应 ``com.paicli.hitl.RendererHitlHandler``。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from paicli_py.hitl.approval_policy import ApprovalPolicy
from paicli_py.hitl.approval_request import ApprovalRequest
from paicli_py.hitl.approval_result import ApprovalDecision, ApprovalResult

if TYPE_CHECKING:
    from paicli_py.render.protocol import Renderer


class RendererHitlHandler:
    """将审批 UI 委托给 Renderer 的 HITL 处理器。

    与 TerminalHitlHandler 的区别：使用 Renderer 的方法展示审批 UI，
    支持 inline/TUI 等各种渲染模式。
    """

    def __init__(self, renderer: Renderer, enabled: bool = True) -> None:
        self._renderer = renderer
        self._enabled = enabled
        self._approved_all_by_tool: set[str] = set()
        self._approved_all_by_server: set[str] = set()

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled

    def is_approved_all_by_tool(self, tool_name: str) -> bool:
        return tool_name in self._approved_all_by_tool

    def is_approved_all_by_server(self, server_name: str) -> bool:
        return server_name in self._approved_all_by_server

    def clear_approved_all(self) -> None:
        self._approved_all_by_tool.clear()
        self._approved_all_by_server.clear()

    def clear_approved_all_for_server(self, server_name: str) -> None:
        self._approved_all_by_server.discard(server_name)

    def request_approval(self, request: ApprovalRequest) -> ApprovalResult:
        """通过渲染器获取审批决策。"""
        if not self._enabled:
            return ApprovalResult.approve()

        if request.tool_name in self._approved_all_by_tool:
            return ApprovalResult.approve()
        server = ApprovalPolicy.mcp_server_name(request.tool_name)
        if server and server in self._approved_all_by_server:
            return ApprovalResult.approve()

        # 委托给渲染器
        result = self._renderer.prompt_approval(request)
        if result.is_approved_all:
            if result.is_approved_all_for_server and server:
                self._approved_all_by_server.add(server)
            else:
                self._approved_all_by_tool.add(request.tool_name)
        return result
