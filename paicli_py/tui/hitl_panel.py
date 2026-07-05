"""TUI HITL 审批面板 —— 对应 com.paicli.tui.hitl 包。"""


class TuiHitlPanel:
    def __init__(self) -> None:
        self._visible = False

    def show(self, message: str) -> str | None:
        self._visible = True
        return None

    def hide(self) -> None:
        self._visible = False
