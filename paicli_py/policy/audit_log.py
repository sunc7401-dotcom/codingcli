"""危险工具调用的结构化审计日志。

对应 ``com.paicli.policy.AuditLog``。

落盘策略：
- 一行一条 JSON（JSONL 格式），按天分文件 audit-YYYY-MM-DD.jsonl
- 默认目录 ~/.paicli/audit
- 写入失败只在 stderr 提示，不抛出
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, ClassVar


# 审批者常量
APPROVER_HITL = "hitl"
APPROVER_POLICY = "policy"
APPROVER_NONE = "none"
APPROVER_MENTION = "mention"

# 结果常量
OUTCOME_ALLOW = "allow"
OUTCOME_DENY = "deny"
OUTCOME_ERROR = "error"

# 日期格式
_DATE_FMT = "%Y-%m-%d"
_MAX_FIELD_CHARS = 1000


@dataclass
class AuditEntry:
    """审计日志条目（对应 Java record AuditEntry）。"""

    timestamp: str
    tool: str
    args: str
    outcome: str
    reason: str | None
    approver: str
    duration_ms: int
    metadata: dict[str, Any] | None = None

    # ── 静态工厂方法 ──────────────────────────────────────

    @classmethod
    def allow(cls, tool: str, args: str, duration_ms: int, metadata: dict | None = None) -> AuditEntry:
        return cls(
            timestamp=datetime.now(timezone.utc).isoformat(),
            tool=tool,
            args=_truncate(args),
            outcome=OUTCOME_ALLOW,
            reason=None,
            approver=APPROVER_NONE,
            duration_ms=duration_ms,
            metadata=metadata,
        )

    @classmethod
    def allow_by_mention(cls, tool: str, args: str, duration_ms: int) -> AuditEntry:
        return cls(
            timestamp=datetime.now(timezone.utc).isoformat(),
            tool=tool,
            args=_truncate(args),
            outcome=OUTCOME_ALLOW,
            reason=None,
            approver=APPROVER_MENTION,
            duration_ms=duration_ms,
        )

    @classmethod
    def deny_by_hitl(cls, tool: str, args: str, reason: str, duration_ms: int) -> AuditEntry:
        return cls(
            timestamp=datetime.now(timezone.utc).isoformat(),
            tool=tool,
            args=_truncate(args),
            outcome=OUTCOME_DENY,
            reason=reason,
            approver=APPROVER_HITL,
            duration_ms=duration_ms,
        )

    @classmethod
    def deny_by_policy(cls, tool: str, args: str, reason: str, duration_ms: int, metadata: dict | None = None) -> AuditEntry:
        return cls(
            timestamp=datetime.now(timezone.utc).isoformat(),
            tool=tool,
            args=_truncate(args),
            outcome=OUTCOME_DENY,
            reason=reason,
            approver=APPROVER_POLICY,
            duration_ms=duration_ms,
            metadata=metadata,
        )

    @classmethod
    def error(cls, tool: str, args: str, reason: str, duration_ms: int, metadata: dict | None = None) -> AuditEntry:
        return cls(
            timestamp=datetime.now(timezone.utc).isoformat(),
            tool=tool,
            args=_truncate(args),
            outcome=OUTCOME_ERROR,
            reason=reason,
            approver=APPROVER_NONE,
            duration_ms=duration_ms,
            metadata=metadata,
        )


class AuditLog:
    """JSONL 格式的审计日志。"""

    @staticmethod
    def _default_audit_dir() -> Path:
        """审计目录: -Dpaicli.audit.dir > PAICLI_AUDIT_DIR > ~/.paicli/audit"""
        prop = os.environ.get("paicli.audit.dir", "")
        if prop: return Path(prop)
        env = os.environ.get("PAICLI_AUDIT_DIR", "")
        if env: return Path(env)
        return Path.home() / ".paicli" / "audit"

    def __init__(self, audit_dir: Path | None = None) -> None:
        self._audit_dir = audit_dir or self._default_audit_dir()
        self._lock = threading.Lock()

    @property
    def audit_dir(self) -> Path:
        return self._audit_dir

    def record(self, entry: AuditEntry) -> None:
        """写入一条审计记录（线程安全）。失败只在 stderr 提示，不影响主流程。"""
        if entry is None:
            return
        try:
            with self._lock:
                self._audit_dir.mkdir(parents=True, exist_ok=True)
            today_file = self._today_file()
            line = json.dumps({
                "timestamp": entry.timestamp,
                "tool": entry.tool,
                "args": entry.args,
                "outcome": entry.outcome,
                "reason": entry.reason,
                "approver": entry.approver,
                "durationMs": entry.duration_ms,
                "metadata": entry.metadata,
            }, ensure_ascii=False)
            with open(today_file, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError as e:
            sys.stderr.write(f"⚠️ 审计日志写入失败: {e}\n")

    def read_recent(self, n: int = 20) -> list[AuditEntry]:
        """读取今天审计文件最近 n 条记录。"""
        if n <= 0:
            return []

        today = self._today_file()
        if not today.is_file():
            return []

        try:
            lines = today.read_text(encoding="utf-8").strip().splitlines()
            start = max(0, len(lines) - n)
            entries: list[AuditEntry] = []
            for line in lines[start:]:
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    entries.append(AuditEntry(
                        timestamp=data.get("timestamp", ""),
                        tool=data.get("tool", ""),
                        args=data.get("args", ""),
                        outcome=data.get("outcome", ""),
                        reason=data.get("reason"),
                        approver=data.get("approver", APPROVER_NONE),
                        duration_ms=data.get("durationMs", 0),
                        metadata=data.get("metadata"),
                    ))
                except json.JSONDecodeError:
                    continue
            return entries
        except OSError:
            return []

    def _today_file(self) -> Path:
        return self._audit_dir / f"audit-{date.today().isoformat()}.jsonl"


# ── 静态工具函数（包内使用）──────────────────────────────

def _truncate(s: str | None) -> str | None:
    if s is None:
        return None
    sanitized = _sanitize(s)
    if len(sanitized) <= _MAX_FIELD_CHARS:
        return sanitized
    return sanitized[:_MAX_FIELD_CHARS] + "...(truncated)"


def _sanitize(s: str | None) -> str | None:
    """清理敏感信息（Bearer token / password / secret 等）。"""
    if s is None:
        return None
    sanitized = re.sub(r"(?i)Bearer\s+[^\s\"'}]+", "Bearer ***", s)
    sanitized = re.sub(
        r'(?i)("?(?:token|key|password|secret|authorization)"?\s*[:=]\s*")([^"]+)(")',
        r'\1***\3', sanitized,
    )
    sanitized = re.sub(
        r'(?i)(\b(?:token|key|password|secret|authorization)\b\s*[:=]\s*)([^\s,}]+)',
        r'\1***', sanitized,
    )
    return sanitized
