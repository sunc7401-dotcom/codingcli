"""LSP 诊断格式化器。

对应 ``com.paicli.lsp.LspDiagnosticFormatter``。
"""

from __future__ import annotations

from suncli_py.lsp.diagnostic import LspDiagnostic, LspDiagnosticReport, LspSeverity


def format_diagnostic(diag: LspDiagnostic) -> str:
    """格式化单条诊断信息。"""
    icon = {LspSeverity.ERROR: "❌", LspSeverity.WARNING: "⚠️", LspSeverity.INFO: "ℹ️", LspSeverity.HINT: "💡"}

    return (
        f"{icon.get(diag.severity, '?')} "
        f"{diag.file_path}:{diag.line}:{diag.column} "
        f"[{diag.severity.value}] {diag.message}"
    )


def format_report(report: LspDiagnosticReport) -> str:
    """格式化诊断报告。"""
    if report.is_empty:
        return "✅ 未发现代码问题。"

    lines: list[str] = [
        f"检查了 {report.files_checked} 个文件",
        f"  ❌ 错误: {report.error_count}",
        f"  ⚠️  警告: {report.warning_count}",
        "",
    ]

    for diag in report.diagnostics[:20]:
        lines.append(format_diagnostic(diag))

    if len(report.diagnostics) > 20:
        lines.append(f"...(还有 {len(report.diagnostics) - 20} 条)")

    return "\n".join(lines)
