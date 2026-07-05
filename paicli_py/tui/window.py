"""TUI 窗口 —— 对应 ``com.paicli.tui.LanternaWindow``。"""


class LanternaWindow:
    """TUI 终端窗口抽象。"""

    def __init__(self) -> None:
        self._size = (80, 24)

    def get_size(self) -> tuple[int, int]:
        return self._size
