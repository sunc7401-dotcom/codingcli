"""TUI 文件树面板 —— 对应 com.paicli.tui.pane.FileTreePane。"""

from pathlib import Path


class FileTreePane:
    def __init__(self, root: str = ".") -> None:
        self._root = Path(root)
        self._files: list[str] = []

    def refresh(self) -> None:
        self._files = [str(p.relative_to(self._root)) for p in self._root.rglob("*") if p.is_file()][:100]
