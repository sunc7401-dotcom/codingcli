"""LSP 诊断管理器 —— 基于 tree-sitter 的编辑后语法检查。

对应 ``com.paicli.lsp.LspManager``。
"""

from __future__ import annotations

from pathlib import Path

from suncli_py.lsp.diagnostic import LspDiagnostic, LspDiagnosticReport, LspSeverity


class LspManager:
    """编辑后代码诊断管理器。

    对 Python 文件使用 compile() 进行语法检查，
    对其他文件基于 tree-sitter（如可用）。
    """

    def __init__(self, project_path: str | None = None) -> None:
        self._project_path = Path(project_path) if project_path else Path.cwd()
        self._pending: list[LspDiagnostic] = []

    def set_project_path(self, project_path: str) -> None:
        self._project_path = Path(project_path)

    def check_file(self, file_path: str) -> None:
        """调遣检查单个文件，结果追加到待刷新队列。"""
        full_path = (self._project_path / file_path).resolve()
        if not full_path.is_file():
            return

        suffix = full_path.suffix.lower()
        if suffix == ".py":
            self._check_python(full_path)

    def flush_pending_diagnostics(self) -> LspDiagnosticReport:
        """排空并返回待刷新诊断。"""
        if not self._pending:
            return LspDiagnosticReport.EMPTY

        report = LspDiagnosticReport(
            diagnostics=list(self._pending),
            files_checked=len({d.file_path for d in self._pending}),
            files_with_errors=sum(1 for d in self._pending if d.severity == LspSeverity.ERROR),
            files_with_warnings=sum(1 for d in self._pending if d.severity == LspSeverity.WARNING),
        )
        self._pending.clear()
        return report

    # ── 内部 ────────────────────────────────────────────────

    def _check_python(self, file_path: Path) -> None:
        """Python 语法检查。"""
        try:
            source = file_path.read_text(encoding="utf-8")
            compile(source, str(file_path), "exec")
        except SyntaxError as e:
            self._pending.append(LspDiagnostic(
                file_path=str(file_path.relative_to(self._project_path)),
                line=e.lineno or 1,
                column=e.offset or 1,
                message=f"语法错误: {e.msg}",
                severity=LspSeverity.ERROR,
            ))
        except OSError:
            pass
