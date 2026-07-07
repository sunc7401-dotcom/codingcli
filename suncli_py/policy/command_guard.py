"""命令快速拒绝：在 execute_command 进入 HITL 审批之前的黑名单 fast-fail。

对应 ``com.paicli.policy.CommandGuard``。

定位：辅助 HITL 而非主防线。黑名单列不全，但能拦住 LLM 容易踩的明显破坏性命令。

设计取舍：
- 不做完整 shell 解析，只做正则模式匹配
- 命令替换段 $(...) 和反引号内的内容以原文存在，正则会一并扫描
- curl / git / 网络命令默认放行，只拦真正破坏性的
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class _DenyRule:
    reason: str
    pattern: re.Pattern


# 9 条拒绝规则（与 Java 版完全一致）
_RULES: list[_DenyRule] = [
    _DenyRule("禁止 sudo 提权", re.compile(r"(?i)\bsudo\b")),
    _DenyRule(
        "禁止 rm -rf 删除全盘或用户目录",
        re.compile(r"(?i)\brm\s+-[a-z]*r[a-z]*f[a-z]*\s+(/|~|\$home)|"
                   r"\brm\s+-[a-z]*f[a-z]*r[a-z]*\s+(/|~|\$home)"),
    ),
    _DenyRule("禁止 mkfs 格式化磁盘", re.compile(r"(?i)\bmkfs(\.|\b)")),
    _DenyRule("禁止 dd 写入裸设备", re.compile(r"(?i)\bdd\b[^\n]*\bof=/dev/")),
    _DenyRule("识别为 fork bomb", re.compile(r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:")),
    _DenyRule(
        "禁止 curl / wget 管道直接执行远端脚本",
        re.compile(r"(?i)\b(curl|wget)\b[^|\n]*\|\s*(sh|bash|zsh|fish|ksh)\b"),
    ),
    _DenyRule("不允许扫描 /、~ 或整个文件系统", re.compile(r"(?i)\bfind\s+(/|~|\$home)")),
    _DenyRule("禁止 chmod 777 全盘", re.compile(r"(?i)\bchmod\s+-R\s+777\s+(/|~)")),
    _DenyRule("禁止 shutdown / reboot / halt", re.compile(r"(?i)\b(shutdown|reboot|halt|poweroff)\b")),
]


def check_command(command: str) -> str | None:
    """校验命令是否安全。

    Returns:
        None 表示放行；非 None 字符串是拒绝原因。
    """
    if not command:
        return None

    normalized = re.sub(r"\s+", " ", command).strip()

    for rule in _RULES:
        if rule.pattern.search(normalized):
            return rule.reason

    return None
