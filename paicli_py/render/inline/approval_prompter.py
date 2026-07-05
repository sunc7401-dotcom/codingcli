"""内联 HITL 审批提示器 —— 单键审批交互。

对应 ``com.paicli.render.inline.InlineApprovalPrompter``。

支持:
- y/Enter: 批准
- a: 本轮始终批准
- n: 拒绝（可选填原因）
- s: 跳过
- m: 修改参数（输入 JSON）
"""

from __future__ import annotations

import json
import sys
import termios
import tty
from dataclasses import dataclass
from enum import Enum


class ApprovalDecision(str, Enum):
    APPROVE = "approve"
    APPROVE_ALL = "approve_all"
    APPROVE_ALL_SERVER = "approve_all_server"
    REJECT = "reject"
    MODIFY = "modify"
    SKIP = "skip"


@dataclass
class ApprovalResult:
    decision: ApprovalDecision
    modified_arguments: str | None = None
    reason: str | None = None

    @classmethod
    def approve(cls) -> ApprovalResult:
        return cls(ApprovalDecision.APPROVE)

    @classmethod
    def approve_all(cls) -> ApprovalResult:
        return cls(ApprovalDecision.APPROVE_ALL)

    @classmethod
    def approve_all_server(cls) -> ApprovalResult:
        return cls(ApprovalDecision.APPROVE_ALL_SERVER)

    @classmethod
    def reject(cls, reason: str = "") -> ApprovalResult:
        return cls(ApprovalDecision.REJECT, reason=reason)

    @classmethod
    def modify(cls, modified: str) -> ApprovalResult:
        return cls(ApprovalDecision.MODIFY, modified_arguments=modified)

    @classmethod
    def skip(cls) -> ApprovalResult:
        return cls(ApprovalDecision.SKIP)

    @property
    def is_approved(self) -> bool:
        return self.decision in (ApprovalDecision.APPROVE, ApprovalDecision.APPROVE_ALL, ApprovalDecision.APPROVE_ALL_SERVER, ApprovalDecision.MODIFY)


class InlineApprovalPrompter:
    """内联 HITL 审批提示器。

    最大尝试次数: 5
    """

    MAX_ATTEMPTS = 5

    def prompt(self, request) -> ApprovalResult:
        """展示审批请求，阻塞等待用户决策。

        Args:
            request: ApprovalRequest 对象（含 tool_name, params_summary 等字段）

        Returns:
            ApprovalResult 决策结果。
        """
        # 打印审批框
        self._print_request(request)

        for _ in range(self.MAX_ATTEMPTS):
            print("\n[y] 批准  [a] 始终批准  [n] 拒绝  [s] 跳过  [m] 修改", end="")
            sys.stdout.flush()

            key = self._read_single_key()
            print()

            if key in ("y", "\r", "\n", ""):
                return ApprovalResult.approve()
            elif key == "a":
                return self._prompt_approve_all_scope(request)
            elif key == "n":
                reason = self._prompt_for_reason()
                return ApprovalResult.reject(reason)
            elif key == "s":
                return ApprovalResult.skip()
            elif key == "m":
                modified = self._prompt_modified_args()
                if modified:
                    return ApprovalResult.modify(modified)
                continue  # 无效 JSON，重试

            print(f"无效输入 '{key}'，请重试")

        # 超过最大尝试次数，保守拒绝
        return ApprovalResult.reject("超过最大尝试次数")

    # ── 内部 ────────────────────────────────────────────────

    @staticmethod
    def _print_request(request) -> None:
        """打印审批请求框。"""
        print()
        print("╔" + "═" * 58 + "╗")
        print(f"║  ⚠️  需要审批{' ' * 50}║")
        print("╠" + "═" * 58 + "╣")
        print(f"║  工具: {request.tool_name:<50} ║")
        if hasattr(request, "reason"):
            print(f"║  原因: {request.reason:<50} ║")
        print(f"║  参数: {request.params_summary[:50]:<50} ║")
        print("╚" + "═" * 58 + "╝")

    @staticmethod
    def _prompt_approve_all_scope(request) -> ApprovalResult:
        """询问批准范围（工具级别还是服务器级别）。"""
        if hasattr(request, "tool_name") and request.tool_name.startswith("mcp__"):
            server = request.tool_name.split("__")[1] if "__" in request.tool_name else "?"
            print(f"[t] 该工具始终批准  [s] {server} 服务器所有工具始终批准")
            key = InlineApprovalPrompter._read_single_key()
            if key == "s":
                return ApprovalResult.approve_all_server()
        return ApprovalResult.approve_all()

    @staticmethod
    def _prompt_for_reason() -> str:
        """读取拒绝原因。"""
        try:
            return input("拒绝原因（可选）: ").strip()
        except (EOFError, KeyboardInterrupt):
            return ""

    @staticmethod
    def _prompt_modified_args() -> str | None:
        """读取修改后的 JSON 参数。"""
        try:
            raw = input("请输入修改后的 JSON 参数: ").strip()
            json.loads(raw)  # 验证 JSON 合法性
            return raw
        except json.JSONDecodeError:
            print("JSON 格式无效，请重试")
            return None
        except (EOFError, KeyboardInterrupt):
            return None

    @staticmethod
    def _read_single_key() -> str:
        """在 raw 模式下读取单键。"""
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
            if ch == "\033":
                # ESC 序列
                ch2 = sys.stdin.read(1)
                if ch2 == "[":
                    sys.stdin.read(1)  # consume the final byte
                return "\033"
            return ch
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
