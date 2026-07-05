"""LSP 诊断数据模型。

对应 ``com.paicli.lsp.LspDiagnostic``、``LspDiagnosticReport``、``LspSeverity``。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class LspSeverity(str, Enum):
    """诊断严重级别。"""
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"
    HINT = "hint"


@dataclass
class LspDiagnostic:
    """单条诊断信息。"""
    file_path: str
    line: int
    column: int
    message: str
    severity: LspSeverity = LspSeverity.ERROR
    source: str = "tree-sitter"


@dataclass
class LspDiagnosticReport:
    """诊断报告 —— 一批文件的检查结果。"""
    diagnostics: list[LspDiagnostic] = field(default_factory=list)
    files_checked: int = 0
    files_with_errors: int = 0
    files_with_warnings: int = 0

    @property
    def is_empty(self) -> bool:
        return len(self.diagnostics) == 0

    @property
    def error_count(self) -> int:
        return sum(1 for d in self.diagnostics if d.severity == LspSeverity.ERROR)

    @property
    def warning_count(self) -> int:
        return sum(1 for d in self.diagnostics if d.severity == LspSeverity.WARNING)

    def merge(self, other: LspDiagnosticReport) -> LspDiagnosticReport:
        """合并两个报告。"""
        return LspDiagnosticReport(
            diagnostics=self.diagnostics + other.diagnostics,
            files_checked=self.files_checked + other.files_checked,
            files_with_errors=self.files_with_errors + other.files_with_errors,
            files_with_warnings=self.files_with_warnings + other.files_with_warnings,
        )

    EMPTY: "LspDiagnosticReport" = None  # type: ignore[assignment]


LspDiagnosticReport.EMPTY = LspDiagnosticReport()
