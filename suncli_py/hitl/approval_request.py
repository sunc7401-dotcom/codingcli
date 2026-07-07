"""审批请求 —— 对应 ``com.paicli.hitl.ApprovalRequest`` record。"""

from __future__ import annotations

import json
from dataclasses import dataclass

from suncli_py.hitl.approval_policy import ApprovalPolicy

BOX_INNER_WIDTH = 58
FIELD_WIDTH = 50
ARG_LINE_WIDTH = 52
MAX_LONG_VALUE_PREVIEW = 120


@dataclass(frozen=True)
class ApprovalRequest:
    tool_name: str
    arguments: str
    danger_level: str = ""
    risk_description: str = ""
    suggestion: str = ""
    caller_context: str = ""
    sensitive_notice: str = ""

    @classmethod
    def of(cls, tool_name: str, arguments: str, suggestion: str = "",
           caller_context: str = "", sensitive_notice: str = "") -> ApprovalRequest:
        return cls(
            tool_name=tool_name,
            arguments=arguments,
            danger_level=ApprovalPolicy.get_danger_level(tool_name),
            risk_description=ApprovalPolicy.get_risk_description(tool_name),
            suggestion=suggestion,
            caller_context=caller_context,
            sensitive_notice=sensitive_notice,
        )

    def to_display_text(self) -> str:
        """将审批请求格式化为带框线的终端展示文本。"""
        lines: list[str] = []
        lines.append("╔" + "═" * BOX_INNER_WIDTH + "╗")
        lines.append(f"║  ⚠️  需要审批{' ' * (BOX_INNER_WIDTH - 9)}║")
        lines.append("╠" + "═" * BOX_INNER_WIDTH + "╣")
        lines.append(f"║  工具: {self.tool_name:<{BOX_INNER_WIDTH - 6}}║")

        if self.caller_context:
            lines.append(f"║  来源: {self.caller_context[:BOX_INNER_WIDTH - 6]:<{BOX_INNER_WIDTH - 6}}║")

        lines.append(f"║  危险级别: {self.danger_level:<{BOX_INNER_WIDTH - 9}}║")
        lines.append(f"║  风险: {self.risk_description[:BOX_INNER_WIDTH - 6]:<{BOX_INNER_WIDTH - 6}}║")

        if self.sensitive_notice:
            lines.append(f"║  {self.sensitive_notice[:BOX_INNER_WIDTH - 2]}║")

        # 参数部分
        args_display = self._format_args(self.arguments)
        for arg_line in args_display.splitlines():
            lines.append(f"║  {arg_line[:BOX_INNER_WIDTH - 2]:<{BOX_INNER_WIDTH - 2}}║")

        if self.suggestion:
            lines.append(f"║  原因: {self.suggestion[:BOX_INNER_WIDTH - 6]:<{BOX_INNER_WIDTH - 6}}║")

        lines.append("╚" + "═" * BOX_INNER_WIDTH + "╝")
        return "\n".join(lines)

    @staticmethod
    def _format_args(args_json: str) -> str:
        """JSON 感知的参数格式化。"""
        try:
            args = json.loads(args_json)
            if isinstance(args, dict):
                lines: list[str] = []
                for k, v in args.items():
                    v_str = str(v)
                    if len(v_str) > MAX_LONG_VALUE_PREVIEW:
                        v_str = v_str[:MAX_LONG_VALUE_PREVIEW] + "..."
                    lines.append(f"  {k}: {v_str}")
                return "\n".join(lines) if lines else args_json[:ARG_LINE_WIDTH]
        except (json.JSONDecodeError, TypeError):
            pass
        return args_json[:ARG_LINE_WIDTH]
