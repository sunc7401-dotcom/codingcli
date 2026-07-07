"""TUI 历史面板 —— 对应 com.paicli.tui.history 包。"""


class TuiHistoryPanel:
    def __init__(self) -> None:
        self._entries: list[str] = []

    def add(self, entry: str) -> None:
        self._entries.append(entry)

    def clear(self) -> None:
        self._entries.clear()
