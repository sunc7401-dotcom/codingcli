"""Agent 循环的退出预算 —— 对应 ``com.paicli.agent.AgentBudget``。"""

from __future__ import annotations

import os
from collections import deque
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from suncli_py.llm.models import ToolCall


class ExitReason(Enum):
    WITHIN_BUDGET = "WITHIN_BUDGET"
    TOKEN_BUDGET_EXCEEDED = "TOKEN_BUDGET_EXCEEDED"
    STAGNATION_DETECTED = "STAGNATION_DETECTED"
    HARD_ITERATION_LIMIT = "HARD_ITERATION_LIMIT"


class AgentBudget:
    DEFAULT_STAGNATION_WINDOW = 3
    DEFAULT_HARD_MAX_ITERATIONS = 50

    def __init__(self, token_budget: int = 2147483647, stagnation_window: int = DEFAULT_STAGNATION_WINDOW,
                 hard_max_iterations: int = DEFAULT_HARD_MAX_ITERATIONS) -> None:
        if token_budget <= 0:
            raise ValueError("token_budget 必须为正整数")
        if stagnation_window < 2:
            raise ValueError("stagnation_window 必须 >= 2")
        if hard_max_iterations <= 0:
            raise ValueError("hard_max_iterations 必须为正整数")
        self._token_budget = token_budget
        self._stagnation_window = stagnation_window
        self._hard_max_iterations = hard_max_iterations
        self._recent_tool_signatures: deque[str] = deque()
        self._iteration: int = 0
        self._total_input_tokens: int = 0
        self._total_output_tokens: int = 0
        self._total_cached_input_tokens: int = 0
        self._stagnant: bool = False

    @classmethod
    def from_system_properties(cls) -> AgentBudget:
        return cls.from_llm_client(None)

    @classmethod
    def from_llm_client(cls, llm_client: object | None) -> AgentBudget:
        return cls(
            token_budget=cls._read_config("paicli.react.token.budget", 2147483647),
            stagnation_window=cls._read_config("paicli.react.stagnation.window", cls.DEFAULT_STAGNATION_WINDOW),
            hard_max_iterations=cls._read_config("paicli.react.hard.max.iterations", cls.DEFAULT_HARD_MAX_ITERATIONS),
        )

    @staticmethod
    def _read_config(key: str, default: int) -> int:
        for candidate in (key, key.replace(".", "_").upper()):
            raw = os.environ.get(candidate, "")
            if raw:
                try:
                    parsed = int(raw.strip())
                    if parsed > 0:
                        return parsed
                except ValueError:
                    continue
        return default

    def begin_iteration(self) -> int:
        self._iteration += 1
        return self._iteration

    def record_tokens(self, input_tokens: int = 0, output_tokens: int = 0, cached_input_tokens: int = 0) -> None:
        self._total_input_tokens += max(0, input_tokens)
        self._total_output_tokens += max(0, output_tokens)
        self._total_cached_input_tokens += max(0, cached_input_tokens)

    def record_tool_calls(self, tool_calls: list[ToolCall] | None) -> None:
        if not tool_calls:
            self._recent_tool_signatures.clear()
            return
        signature = ";".join(f"{tc.name}|{tc.arguments}" for tc in tool_calls)
        self._recent_tool_signatures.append(signature)
        while len(self._recent_tool_signatures) > self._stagnation_window:
            self._recent_tool_signatures.popleft()
        if len(self._recent_tool_signatures) == self._stagnation_window:
            first = self._recent_tool_signatures[0]
            self._stagnant = all(s == first for s in self._recent_tool_signatures)

    def check(self) -> ExitReason:
        if self._stagnant:
            return ExitReason.STAGNATION_DETECTED
        if self._total_input_tokens + self._total_output_tokens >= self._token_budget:
            return ExitReason.TOKEN_BUDGET_EXCEEDED
        if self._iteration >= self._hard_max_iterations:
            return ExitReason.HARD_ITERATION_LIMIT
        return ExitReason.WITHIN_BUDGET

    @property
    def iteration(self) -> int:
        return self._iteration

    @property
    def total_input_tokens(self) -> int:
        return self._total_input_tokens

    @property
    def total_output_tokens(self) -> int:
        return self._total_output_tokens

    @property
    def total_cached_input_tokens(self) -> int:
        return self._total_cached_input_tokens

    @property
    def token_budget(self) -> int:
        return self._token_budget

    @property
    def hard_max_iterations(self) -> int:
        return self._hard_max_iterations

    @property
    def stagnation_window(self) -> int: return self._stagnation_window

    def describe_exit(self, reason: ExitReason) -> str:
        total = self._total_input_tokens + self._total_output_tokens
        match reason:
            case ExitReason.WITHIN_BUDGET: return "未触发兜底条件"
            case ExitReason.TOKEN_BUDGET_EXCEEDED: return f"Token 预算已用尽（{total} / {self._token_budget}），任务被强制收尾"
            case ExitReason.STAGNATION_DETECTED: return f"检测到连续 {self._stagnation_window} 轮重复的工具调用，疑似死循环，已强制收尾"
            case ExitReason.HARD_ITERATION_LIMIT: return f"达到硬轮数上限（{self._hard_max_iterations}），已强制收尾"
