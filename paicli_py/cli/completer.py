"""Tab 补全器 —— 对应 ``com.paicli.cli.PaiCliCompleter``。

基于 prompt_toolkit 的 Completer 实现。
"""

from __future__ import annotations

from prompt_toolkit.completion import Completer, Completion


class PaiCliCompleter(Completer):
    """PaiCLI 的 Tab 补全器。

    支持补全：
    - 斜杠命令（/model, /exit, ...）
    - MCP 资源引用（@server:...）
    - 文件路径（@path）
    """

    COMMANDS = [
        "/exit", "/quit", "/cancel", "/clear", "/compact",
        "/history clear", "/init",
        "/model", "/plan", "/team", "/hitl", "/hitl on", "/hitl off",
        "/memory", "/memory list", "/memory search ", "/memory delete ",
        "/memory clear", "/save ",
        "/index", "/search ", "/graph ",
        "/context", "/policy",
        "/config", "/audit ",
        "/snapshot", "/restore",
        "/mcp", "/mcp restart ", "/mcp logs ", "/mcp disable ", "/mcp enable ",
        "/mcp resources ", "/mcp prompts ",
        "/browser", "/wechat", "/task",
        "/skill", "/skill list", "/skill show ", "/skill on ", "/skill off ",
        "/skill reload", "/export",
    ]

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor

        # 斜杠命令补全
        if text.startswith("/"):
            for cmd in self.COMMANDS:
                if cmd.startswith(text):
                    yield Completion(cmd, start_position=-len(text))

        # @提及补全
        elif text.startswith("@"):
            # 简单的文件路径补全
            from pathlib import Path
            query = text[1:]
            base = Path.cwd()
            try:
                for p in base.glob(f"{query}*"):
                    display = p.name + ("/" if p.is_dir() else "")
                    yield Completion(f"@{p.name}", display=display, start_position=-len(text))
            except Exception:
                pass
