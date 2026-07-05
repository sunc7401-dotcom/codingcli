"""TUI 对话快照 —— 对应 ``com.paicli.tui.history.ConversationSnapshot``。"""


class ConversationSnapshot:
    """对话历史快照视图。"""

    def __init__(self) -> None:
        self._turns: list[dict] = []

    def add_turn(self, user_input: str, assistant_output: str) -> None:
        self._turns.append({"user": user_input, "assistant": assistant_output})

    @property
    def turns(self) -> list[dict]:
        return list(self._turns)
