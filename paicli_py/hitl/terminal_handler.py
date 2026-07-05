"""终端交互式 HITL 审批处理器 —— 对应 ``com.paicli.hitl.TerminalHitlHandler``。"""

from __future__ import annotations

import sys
import threading

from paicli_py.hitl.approval_policy import ApprovalPolicy
from paicli_py.hitl.approval_request import ApprovalRequest
from paicli_py.hitl.approval_result import ApprovalDecision, ApprovalResult


class TerminalHitlHandler:
    """终端交互式审批处理器（同步阻塞 stdin，线程安全）。"""

    def __init__(self, enabled: bool = True) -> None:
        self._enabled = enabled
        self._lock = threading.Lock()
        self._approved_all_by_tool: set[str] = set()
        self._approved_all_by_server: set[str] = set()

    def is_enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled

    def is_approved_all_by_tool(self, tool_name: str) -> bool:
        return tool_name in self._approved_all_by_tool

    def is_approved_all_by_server(self, server_name: str) -> bool:
        return server_name in self._approved_all_by_server

    def clear_approved_all(self) -> None:
        with self._lock:
            self._approved_all_by_tool.clear()
            self._approved_all_by_server.clear()

    def clear_approved_all_for_server(self, server_name: str) -> None:
        with self._lock:
            self._approved_all_by_server.discard(server_name)

    def request_approval(self, request: ApprovalRequest) -> ApprovalResult:
        """展示审批请求，阻塞等待用户决策（同步方法，线程安全）。"""
        with self._lock:
            # 批量批准检查
            if request.tool_name in self._approved_all_by_tool:
                return ApprovalResult.approve_all()

            server = ApprovalPolicy.mcp_server_name(request.tool_name)
            if server and server in self._approved_all_by_server:
                return ApprovalResult.approve_all_by_server()

            # 打印审批提示
            print()
            print("────────── ⚠️  HITL 审批请求 ──────────")
            print(request.to_display_text())

            return self._prompt_until_decision(request)

    def _prompt_until_decision(self, request: ApprovalRequest) -> ApprovalResult:
        """主交互循环（最多 5 次尝试）。"""
        is_sensitive = bool(request.sensitive_notice)

        for _ in range(5):
            try:
                if is_sensitive:
                    print("\n[y/Enter] 批准  [n] 拒绝  [s] 跳过  [m] 修改", end="")
                else:
                    print("\n[y/Enter] 批准  [a] 始终批准  [n] 拒绝  [s] 跳过  [m] 修改", end="")
                sys.stdout.flush()
                choice = input().strip().lower()
            except (EOFError, KeyboardInterrupt):
                return ApprovalResult.reject("用户取消")

            if choice in ("y", ""):
                return ApprovalResult.approve()
            elif choice == "a" and not is_sensitive:
                return self._prompt_approve_all_scope(request)
            elif choice == "n":
                reason = ""
                try:
                    reason = input("拒绝原因（可选）: ").strip()
                except (EOFError, KeyboardInterrupt):
                    pass
                return ApprovalResult.reject(reason)
            elif choice == "s":
                return ApprovalResult.skip()
            elif choice == "m":
                import json
                try:
                    modified = input("请输入修改后的 JSON 参数: ").strip()
                    json.loads(modified)
                    return ApprovalResult.modify(modified)
                except (json.JSONDecodeError, ValueError):
                    print("JSON 格式无效，请重试")
                    continue

            print(f"无效输入: '{choice}'，请重试")

        return ApprovalResult.reject("超过最大尝试次数")

    def _prompt_approve_all_scope(self, request: ApprovalRequest) -> ApprovalResult:
        """询问批准范围。"""
        server = ApprovalPolicy.mcp_server_name(request.tool_name)
        if server:
            print(f"[t] 该工具始终批准  [s] {server} 服务器所有工具始终批准")
            try:
                choice = input().strip().lower()
            except (EOFError, KeyboardInterrupt):
                return ApprovalResult.approve_all()
            if choice == "s":
                self._approved_all_by_server.add(server)
                return ApprovalResult.approve_all_by_server()

        self._approved_all_by_tool.add(request.tool_name)
        return ApprovalResult.approve_all()
