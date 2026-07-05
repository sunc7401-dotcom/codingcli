"""HITL 处理器接口 —— 对应 ``com.paicli.hitl.HitlHandler``。"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from paicli_py.hitl.approval_request import ApprovalRequest
from paicli_py.hitl.approval_result import ApprovalResult


@runtime_checkable
class HitlHandler(Protocol):
    """人机协同审批处理器协议。"""

    def request_approval(self, request: ApprovalRequest) -> ApprovalResult:
        """展示审批请求，等待用户决策（同步阻塞）。"""
        ...

    def is_enabled(self) -> bool:
        """HITL 是否启用。"""
        return True

    def set_enabled(self, enabled: bool) -> None:
        """启用/禁用 HITL。"""
        ...

    def is_approved_all_by_tool(self, tool_name: str) -> bool:
        """检查是否已对该工具"始终批准"。"""
        return False

    def is_approved_all_by_server(self, server_name: str) -> bool:
        """检查是否已对该 MCP 服务器"始终批准"。"""
        return False

    def clear_approved_all(self) -> None:
        """清除所有"始终批准"记录。"""
        pass

    def clear_approved_all_for_server(self, server_name: str) -> None:
        """清除指定服务器的"始终批准"记录。"""
        pass
