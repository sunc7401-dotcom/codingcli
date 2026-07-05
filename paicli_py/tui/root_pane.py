"""TUI 根面板 —— 对应 ``com.paicli.tui.RootPane``。"""


class RootPane:
    """TUI 主布局面板。"""

    def __init__(self) -> None:
        self._components: dict[str, object] = {}

    def add(self, name: str, component: object) -> None:
        self._components[name] = component
