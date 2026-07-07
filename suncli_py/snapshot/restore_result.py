"""恢复结果模型 —— 对应 ``com.paicli.snapshot.RestoreResult``。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RestoreResult:
    success: bool
    restored_files: list[str] = field(default_factory=list)
    deleted_files: list[str] = field(default_factory=list)
    error: str | None = None
