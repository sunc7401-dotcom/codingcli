"""TUI 面板子包。"""

from paicli_py.tui.center_pane import CenterPane
from paicli_py.tui.file_tree_pane import FileTreePane
from paicli_py.tui.input_bar import InputBar as TuiInputBar
from paicli_py.tui.status_pane import TuiStatusPane as StatusPane

__all__ = ["CenterPane", "FileTreePane", "TuiInputBar", "StatusPane"]
