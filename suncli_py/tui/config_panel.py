"""TUI 配置面板 —— 对应 com.paicli.tui.config 包。"""


class TuiConfigPanel:
    def __init__(self) -> None:
        self._settings: dict[str, str] = {}

    def get(self, key: str, default: str = "") -> str:
        return self._settings.get(key, default)

    def set(self, key: str, value: str) -> None:
        self._settings[key] = value
