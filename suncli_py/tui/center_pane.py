"""TUI 中央面板 —— 对应 com.paicli.tui.pane 包。"""


class CenterPane:
    def __init__(self) -> None:
        self._content: list[str] = []

    def append(self, text: str) -> None:
        self._content.append(text)

    def clear(self) -> None:
        self._content.clear()

    def render(self) -> str:
        return "\n".join(self._content)
