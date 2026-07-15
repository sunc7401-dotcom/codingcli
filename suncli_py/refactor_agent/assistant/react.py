"""Reusable ReAct runtime and agent-to-agent message protocol."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from collections import deque
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from loguru import logger

from suncli_py.llm.client import LlmClient
from suncli_py.llm.models import Message, ToolCall
from suncli_py.memory.manager import MemoryManager

JsonValidator = Callable[[dict[str, Any]], str | None]


class AgentRole(StrEnum):
    TEST_GENERATOR = "TEST_GENERATOR"
    MODIFIER = "MODIFIER"
    VERIFIER = "VERIFIER"


class AgentMessageType(StrEnum):
    TASK = "TASK"
    RESULT = "RESULT"
    FEEDBACK = "FEEDBACK"
    APPROVAL = "APPROVAL"
    REJECTION = "REJECTION"
    ERROR = "ERROR"


@dataclass(frozen=True)
class AgentMessage:
    from_agent: str
    from_role: AgentRole | None
    content: str
    type: AgentMessageType

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def task(cls, content: str) -> AgentMessage:
        return cls("orchestrator", None, content, AgentMessageType.TASK)

    @classmethod
    def result(cls, agent: str, role: AgentRole, content: str) -> AgentMessage:
        return cls(agent, role, content, AgentMessageType.RESULT)

    @classmethod
    def feedback(cls, content: str) -> AgentMessage:
        return cls("verifier", AgentRole.VERIFIER, content, AgentMessageType.FEEDBACK)

    @classmethod
    def approval(cls, content: str) -> AgentMessage:
        return cls("verifier", AgentRole.VERIFIER, content, AgentMessageType.APPROVAL)

    @classmethod
    def rejection(cls, content: str) -> AgentMessage:
        return cls("verifier", AgentRole.VERIFIER, content, AgentMessageType.REJECTION)

    @classmethod
    def error(cls, agent: str, role: AgentRole, content: str) -> AgentMessage:
        return cls(agent, role, content, AgentMessageType.ERROR)


class ReactToolRuntime(Protocol):
    def schemas(self) -> list[dict[str, Any]]: ...

    def execute(self, name: str, arguments: dict[str, Any]) -> str: ...

    def is_read_only(self, name: str) -> bool: ...


class AgentExitReason(StrEnum):
    WITHIN_BUDGET = "within_budget"
    TOKEN_BUDGET_EXCEEDED = "token_budget_exceeded"
    STAGNATION_DETECTED = "stagnation_detected"
    HARD_ITERATION_LIMIT = "hard_iteration_limit"


@dataclass
class AgentBudget:
    token_budget: int = sys.maxsize
    stagnation_window: int = 3
    hard_max_iterations: int = 50
    iteration: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cached_input_tokens: int = 0
    _signatures: deque[str] = field(default_factory=deque)
    _stagnant: bool = False

    def __post_init__(self) -> None:
        if self.token_budget <= 0:
            raise ValueError("token_budget must be positive")
        if self.stagnation_window < 2:
            raise ValueError("stagnation_window must be >= 2")
        if self.hard_max_iterations <= 0:
            raise ValueError("hard_max_iterations must be positive")

    @classmethod
    def from_environment(cls) -> AgentBudget:
        return cls(
            token_budget=_positive_env("PAICLI_REACT_TOKEN_BUDGET", sys.maxsize),
            stagnation_window=_positive_env("PAICLI_REACT_STAGNATION_WINDOW", 3, minimum=2),
            hard_max_iterations=_positive_env("PAICLI_REACT_HARD_MAX_ITERATIONS", 50),
        )

    def begin_iteration(self) -> int:
        self.iteration += 1
        return self.iteration

    def record_tokens(self, input_tokens: int, output_tokens: int, cached_input_tokens: int = 0) -> None:
        self.total_input_tokens += max(0, input_tokens)
        self.total_output_tokens += max(0, output_tokens)
        self.total_cached_input_tokens += max(0, cached_input_tokens)

    def record_tool_calls(self, calls: list[ToolCall]) -> None:
        if not calls:
            self._signatures.clear()
            self._stagnant = False
            return
        signature = ";".join(f"{call.name}|{call.arguments}" for call in calls)
        self._signatures.append(signature)
        while len(self._signatures) > self.stagnation_window:
            self._signatures.popleft()
        if len(self._signatures) == self.stagnation_window:
            first = self._signatures[0]
            self._stagnant = all(item == first for item in self._signatures)

    def check(self) -> AgentExitReason:
        if self._stagnant:
            return AgentExitReason.STAGNATION_DETECTED
        if self.total_input_tokens + self.total_output_tokens >= self.token_budget:
            return AgentExitReason.TOKEN_BUDGET_EXCEEDED
        if self.iteration >= self.hard_max_iterations:
            return AgentExitReason.HARD_ITERATION_LIMIT
        return AgentExitReason.WITHIN_BUDGET

    def describe(self, reason: AgentExitReason) -> str:
        if reason == AgentExitReason.TOKEN_BUDGET_EXCEEDED:
            return (
                "ReAct token budget exhausted: "
                f"{self.total_input_tokens + self.total_output_tokens}/{self.token_budget}"
            )
        if reason == AgentExitReason.STAGNATION_DETECTED:
            return f"ReAct stopped after {self.stagnation_window} identical tool-call rounds."
        if reason == AgentExitReason.HARD_ITERATION_LIMIT:
            return f"ReAct reached the hard iteration limit: {self.hard_max_iterations}."
        return "ReAct is within budget."


@dataclass(frozen=True)
class ToolTrace:
    iteration: int
    name: str
    arguments: dict[str, Any]
    output: str
    duration_ms: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ReactRunResult:
    data: dict[str, Any] | None
    content: str
    traces: list[ToolTrace]
    error: str = ""
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def succeeded(self) -> bool:
        return self.data is not None and not self.error


class ReactAgent:
    """Stateful ReAct agent whose normal exit is decided by the LLM."""

    def __init__(
        self,
        *,
        name: str,
        client: LlmClient,
        root: Path,
        system_prompt: str,
        role: AgentRole | None = None,
        tools: ReactToolRuntime | None = None,
        memory: MemoryManager | None = None,
        budget_factory: Callable[[], AgentBudget] = AgentBudget.from_environment,
    ) -> None:
        self.name = name
        self.role = role
        self.client = client
        self.root = root.resolve()
        self.system_prompt = system_prompt
        self.tools = tools
        self.memory = memory or MemoryManager(client, self.root)
        self.budget_factory = budget_factory
        self.history: list[Message] = [Message.system(system_prompt)]

    def reset_history(self) -> None:
        self.history[:] = [Message.system(self.system_prompt)]

    def run_json(self, task: str, *, validator: JsonValidator | None = None) -> ReactRunResult:
        memory_context = self.memory.prompt_context(task)
        self.history[0] = Message.system(
            self.system_prompt + ("\n\n" + memory_context if memory_context else "")
        )
        self.history.append(Message.user(task))
        self.memory.add_user_message(task)
        budget = self.budget_factory()
        traces: list[ToolTrace] = []
        schemas = self.tools.schemas() if self.tools is not None else None

        while True:
            exit_reason = budget.check()
            if exit_reason != AgentExitReason.WITHIN_BUDGET:
                error = budget.describe(exit_reason)
                logger.warning("[{}] {}", self.name, error)
                return ReactRunResult(
                    data=None,
                    content="",
                    traces=traces,
                    error=error,
                    input_tokens=budget.total_input_tokens,
                    output_tokens=budget.total_output_tokens,
                )

            iteration = budget.begin_iteration()
            try:
                _run_async(self.memory.compact_history_if_needed(self.history))
                response = _run_async(self.client.chat(messages=self.history, tools=schemas))
            except Exception as err:
                error = f"LLM request failed: {err}"
                return ReactRunResult(None, "", traces, error, budget.total_input_tokens, budget.total_output_tokens)
            if response is None:
                return ReactRunResult(None, "", traces, "LLM returned no response.")

            budget.record_tokens(
                response.input_tokens,
                response.output_tokens,
                response.cached_input_tokens,
            )
            if response.has_tool_calls() and self.tools is not None:
                calls = response.tool_calls or []
                budget.record_tool_calls(calls)
                self.history.append(
                    Message.assistant(
                        content=response.content,
                        reasoning_content=response.reasoning_content,
                        tool_calls=calls,
                    )
                )
                try:
                    round_traces = _run_async(_execute_tool_calls(self.tools, calls, iteration))
                except Exception as err:
                    error = f"Tool execution failed: {err}"
                    return ReactRunResult(
                        None,
                        "",
                        traces,
                        error,
                        budget.total_input_tokens,
                        budget.total_output_tokens,
                    )
                traces.extend(round_traces)
                for call, trace in zip(calls, round_traces, strict=True):
                    self.history.append(Message.tool(call.id, trace.output))
                    self.memory.add_tool_result(trace.name, trace.output)
                continue

            budget.record_tool_calls([])
            content = response.content or ""
            self.history.append(
                Message.assistant(content, reasoning_content=response.reasoning_content)
            )
            data = parse_json_object(content)
            validation_error = "Final response is not a valid JSON object."
            if data is not None and validator is not None:
                validation_error = validator(data) or ""
            elif data is not None:
                validation_error = ""
            if not validation_error:
                self.memory.add_assistant_message(content)
                return ReactRunResult(
                    data=data,
                    content=content,
                    traces=traces,
                    input_tokens=budget.total_input_tokens,
                    output_tokens=budget.total_output_tokens,
                )

            self.history.append(
                Message.user(
                    "Your final response was rejected by the runtime: "
                    f"{validation_error} Return only a corrected JSON object."
                )
            )


def parse_json_object(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start < 0 or end < start:
        return None
    try:
        value = json.loads(stripped[start : end + 1])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


async def _execute_tool_calls(
    tools: ReactToolRuntime,
    calls: list[ToolCall],
    iteration: int,
) -> list[ToolTrace]:
    if not calls:
        return []
    if len(calls) > 1 and all(tools.is_read_only(call.name) for call in calls):
        logger.info("Executing {} independent tools in parallel", len(calls))
        started = time.monotonic()
        parallel_results = list(
            await asyncio.gather(
                *[_execute_one(tools, call, iteration) for call in calls]
            )
        )
        logger.info("Completed {} tool(s) in {:.0f} ms", len(calls), (time.monotonic() - started) * 1000)
        return parallel_results
    serial_results: list[ToolTrace] = []
    for call in calls:
        serial_results.append(await _execute_one(tools, call, iteration))
    return serial_results


async def _execute_one(tools: ReactToolRuntime, call: ToolCall, iteration: int) -> ToolTrace:
    arguments = _safe_tool_arguments(call.arguments)
    started = time.monotonic()
    output = await asyncio.to_thread(tools.execute, call.name, arguments)
    return ToolTrace(
        iteration=iteration,
        name=call.name,
        arguments=arguments,
        output=output,
        duration_ms=round((time.monotonic() - started) * 1000),
    )


def _safe_tool_arguments(arguments: str) -> dict[str, Any]:
    try:
        data = json.loads(arguments or "{}")
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _positive_env(name: str, default: int, *, minimum: int = 1) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value >= minimum else default


_SYNC_LOOP: asyncio.AbstractEventLoop | None = None


def _run_async(coro: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return _run_on_sync_loop(coro)
    close = getattr(coro, "close", None)
    if callable(close):
        close()
    raise RuntimeError("Cannot run synchronous refactor-agent LLM call inside an active asyncio event loop.")


def _run_on_sync_loop(coro: Any) -> Any:
    global _SYNC_LOOP
    if _SYNC_LOOP is None or _SYNC_LOOP.is_closed():
        _SYNC_LOOP = asyncio.new_event_loop()
    return _SYNC_LOOP.run_until_complete(coro)


def _close_sync_loop_for_tests() -> None:
    global _SYNC_LOOP
    if _SYNC_LOOP is not None and not _SYNC_LOOP.is_closed():
        _SYNC_LOOP.close()
    _SYNC_LOOP = None


def _sync_loop_id_for_tests() -> int | None:
    return id(_SYNC_LOOP) if _SYNC_LOOP is not None and not _SYNC_LOOP.is_closed() else None


def _reset_sync_loop_for_tests() -> None:
    _close_sync_loop_for_tests()
