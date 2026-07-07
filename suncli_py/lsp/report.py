"""LSP 诊断报告 —— 对应 ``com.paicli.lsp.LspDiagnosticReport``。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class LspDiagnosticReport:
    prompt_text: str = ""
    display_text: str = ""

    @property
    def is_empty(self) -> bool:
        return not self.prompt_text and not self.display_text

    EMPTY: LspDiagnosticReport = None  # type: ignore


LspDiagnosticReport.EMPTY = LspDiagnosticReport()
