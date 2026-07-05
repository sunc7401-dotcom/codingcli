"""纯文本渲染器 —— 最简单的 stdout 输出。

对应 ``com.paicli.render.PlainRenderer``。
"""

from __future__ import annotations

from paicli_py.render.protocol import Renderer, StatusInfo


class PlainRenderer(Renderer):
    """纯文本渲染器，所有输出直接打印到 stdout。"""

    def start(self) -> None:
        print("PaiCLI v16.1.0 (Python) - 纯文本模式")

    def begin_turn(self, user_input: str) -> None:
        print(f"\n{'='*60}")

    def stream(self, text: str) -> None:
        print(text, end="", flush=True)

    def append_tool_calls(self, tool_calls: list[dict]) -> None:
        print(f"\n🔧 工具调用: {len(tool_calls)} 个")

    def append_tool_result(self, tool_name: str, result: str) -> None:
        preview = result[:200] + "..." if len(result) > 200 else result
        print(f"📋 [{tool_name}]: {preview}")

    def append_diff(self, file_path: str, diff_text: str) -> None:
        print(f"📝 文件变更: {file_path}")

    def update_status(self, status: StatusInfo) -> None:
        pass  # 纯文本模式不显示状态栏

    def prompt_approval(self, message: str) -> bool:
        print(f"\n⚠️  审批: {message}")
        try:
            choice = input("[y/N] ").strip().lower()
            return choice == "y"
        except (EOFError, KeyboardInterrupt):
            return False

    def finish_turn(self, final_answer: str) -> None:
        print(f"\n{'='*60}\n")

    def shutdown(self) -> None:
        print("\n再见！")
