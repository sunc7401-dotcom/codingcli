"""TUI 输入栏 —— 对应 com.paicli.tui.pane 包。"""


class TuiInputBar:
    def __init__(self) -> None:
        self._text = ""

    def set_text(self, text: str) -> None:
        self._text = text

    def clear(self) -> None:
        self._text = ""
