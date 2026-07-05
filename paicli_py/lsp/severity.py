"""LSP 严重级别 —— 对应 ``com.paicli.lsp.LspSeverity``。"""

from enum import Enum


class LspSeverity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"
