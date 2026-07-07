"""浏览器检查结果 —— 对应 ``com.paicli.browser.BrowserCheckResult`` record。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class BrowserCheckResult:
    blocked: bool = False
    reason: str = ""
    requires_per_call_approval: bool = False
    sensitive_notice: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def allow(cls, metadata: dict | None = None) -> BrowserCheckResult:
        return cls(metadata=metadata or {})

    @classmethod
    def block(cls, reason: str, metadata: dict | None = None) -> BrowserCheckResult:
        return cls(blocked=True, reason=reason, metadata=metadata or {})

    @classmethod
    def require_approval(cls, notice: str, metadata: dict | None = None) -> BrowserCheckResult:
        return cls(requires_per_call_approval=True, sensitive_notice=notice, metadata=metadata or {})
