"""可切换的 HITL 处理器 —— 对应 ``com.paicli.hitl.SwitchableHitlHandler``。"""

from __future__ import annotations

from paicli_py.hitl.approval_request import ApprovalRequest
from paicli_py.hitl.approval_result import ApprovalResult
from paicli_py.hitl.hitl_handler import HitlHandler


class SwitchableHitlHandler:
    """装饰器/代理模式：在运行时切换底层 HITL 处理器。

    关键设计：ToolRegistry 在 UI 模式选定之前就创建，
    SwitchableHitlHandler 将构造时机与运行时 UI 模式解耦。
    """

    def __init__(self, delegate: HitlHandler) -> None:
        if delegate is None:
            raise ValueError("delegate 不能为空")
        self._delegate = delegate

    @property
    def delegate(self) -> HitlHandler:
        return self._delegate

    def set_delegate(self, delegate: HitlHandler) -> None:
        if delegate is None:
            raise ValueError("delegate 不能为空")
        self._delegate = delegate

    @property
    def enabled(self) -> bool:
        return self._delegate.enabled

    def request_approval(self, request: ApprovalRequest) -> ApprovalResult:
        return self._delegate.request_approval(request)

    def is_approved_all_by_tool(self, tool_name: str) -> bool:
        return self._delegate.is_approved_all_by_tool(tool_name)

    def is_approved_all_by_server(self, server_name: str) -> bool:
        return self._delegate.is_approved_all_by_server(server_name)

    def clear_approved_all(self) -> None:
        self._delegate.clear_approved_all()

    def clear_approved_all_for_server(self, server_name: str) -> None:
        self._delegate.clear_approved_all_for_server(server_name)
