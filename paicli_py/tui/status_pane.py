"""TUI 状态面板 —— 对应 com.paicli.tui.pane.StatusPane。"""


class TuiStatusPane:
    def __init__(self) -> None:
        self._text = ""

    def update(self, text: str) -> None:
        self._text = text
