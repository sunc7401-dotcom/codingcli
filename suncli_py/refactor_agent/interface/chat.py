"""Command-only interactive shell for the Java refactor-agent."""

from __future__ import annotations

import json
import re
import shlex
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from suncli_py.config.config import PaiCliConfig
from suncli_py.llm.client import LlmClient
from suncli_py.llm.factory import create_client_from_config
from suncli_py.llm.models import Message
from suncli_py.memory.manager import MemoryManager
from suncli_py.memory.models import MemoryEntry, MemoryType
from suncli_py.memory.project import ProjectMemoryInitializer
from suncli_py.memory.storage import LongTermMemory
from suncli_py.refactor_agent.assistant.llm_assistant import _run_async
from suncli_py.refactor_agent.assistant.toolbox import RefactorAgentToolbox
from suncli_py.refactor_agent.core.storage import RefactorAgentStorage
from suncli_py.refactor_agent.interface.commands import (
    RefactorAgentError,
    run_apply,
    run_characterize,
    run_plan,
    run_report,
    run_rollback,
    run_scan,
)

IssueId = str | None
Printer = Callable[[str], None]

ISSUE_RE = re.compile(r"\bRA-\d{4,}\b", re.IGNORECASE)


HELP_TEXT = """Commands:
  scan
  issues
  select RA-0001
  plan RA-0001
  apply RA-0001
  apply RA-0001 --yes --max-repair-attempts 2
  characterize RA-0001
  characterize RA-0001 --yes
  report
  rollback
  rollback --yes
  status
  /memory [list|search QUERY|delete ID|clear]
  /save [--global] FACT
  /init [--force]
  /compact
  /clear
  help
  exit

Any other input starts a multi-turn project-assistant conversation.
""".strip()


@dataclass
class RefactorChatSession:
    root: Path | str = "."
    scan_handler: Callable[..., int] = run_scan
    plan_handler: Callable[..., int] = run_plan
    apply_handler: Callable[..., int] = run_apply
    characterize_handler: Callable[..., int] = run_characterize
    rollback_handler: Callable[..., int] = run_rollback
    report_handler: Callable[..., int] = run_report
    printer: Printer = print
    selected_issue_id: IssueId = None
    client: LlmClient | None = None
    long_term_memory: LongTermMemory | None = None
    resolved_root: Path = field(init=False)
    active_long_term: LongTermMemory = field(init=False)

    def __post_init__(self) -> None:
        self.resolved_root = Path(self.root).resolve()
        self.root = self.resolved_root
        self.storage = RefactorAgentStorage(self.resolved_root)
        self.active_long_term = self.long_term_memory or LongTermMemory()
        self.memory: MemoryManager | None = None
        self.history: list[Message] = []

    def run(self) -> int:
        self.printer("LLM-driven refactor-CLI command shell")
        self.printer(f"Project root: {self.root}")
        self.printer("Type help for commands, exit to quit.")
        while True:
            try:
                message = input("refactor-agent> ")
            except (EOFError, KeyboardInterrupt):
                self.printer("")
                return 0
            if not self.handle_message(message):
                return 0

    def handle_message(self, message: str) -> bool:
        argv = _split_command(message)
        if not argv:
            return True

        command = argv[0].lower()
        try:
            if command in {"exit", "quit", "q"}:
                self.printer("bye")
                return False
            if command in {"help", "?"}:
                self.printer(HELP_TEXT)
                return True
            if command in {"/memory", "/mem"}:
                self._handle_memory(argv)
                return True
            if command == "/save":
                self._handle_save(argv)
                return True
            if command == "/init":
                self._handle_init(argv)
                return True
            if command == "/compact":
                self._handle_compact()
                return True
            if command == "/clear":
                self.history.clear()
                if self.memory:
                    self.memory.clear_short_term()
                self.printer("Conversation history cleared; long-term memory was preserved.")
                return True
            if command == "status":
                self._show_status()
                return True
            if command in {"issues", "list", "ls"}:
                self._list_issues()
                return True
            if command == "scan":
                self._run_scan()
                return True
            if command == "select":
                self._select_issue(argv)
                return True
            if command == "plan":
                self._run_plan(argv)
                return True
            if command == "apply":
                self._run_apply(argv)
                return True
            if command == "verify":
                self.printer("独立 verify 已取消；请执行 apply，修改后会自动调用验证 Agent。")
                return True
            if command == "characterize":
                self._run_characterize(argv)
                return True
            if command == "rollback":
                self._run_rollback(argv)
                return True
            if command == "report":
                self._run_report()
                return True
        except RefactorAgentError as err:
            self.printer(f"error: {err}")
            return True

        self._run_assistant(message)
        return True

    def _ensure_memory(self) -> MemoryManager | None:
        if self.memory is not None:
            return self.memory
        if self.client is None:
            self.client = create_client_from_config(PaiCliConfig.load())
        if self.client is None:
            self.printer("error: no configured LLM provider; configure an API key before using natural-language chat")
            return None
        self.memory = MemoryManager(self.client, self.resolved_root, long_term=self.active_long_term)
        return self.memory

    def _run_assistant(self, user_input: str) -> None:
        memory = self._ensure_memory()
        if memory is None or self.client is None:
            return
        memory.add_user_message(user_input)
        context = memory.prompt_context(user_input)
        system = (
            "You are a project assistant for a Java Maven refactoring repository. Answer questions using repository "
            "evidence. Use read_file/search_code when useful. Never modify files or execute commands from chat. "
            "Call save_memory only when the user explicitly asks you to remember a durable fact or preference."
        )
        if context:
            system += "\n\n" + context
        if self.history and self.history[0].role == "system":
            self.history[0] = Message.system(system)
        else:
            self.history.insert(0, Message.system(system))
        self.history.append(Message.user(user_input))
        _run_async(memory.compact_short_term_if_needed())
        _run_async(memory.compact_history_if_needed(self.history))
        try:
            response = _run_async(self._chat_with_tools())
        except (OSError, RuntimeError) as err:
            self.printer(f"error: LLM request failed: {err}")
            return
        if not response:
            self.printer("error: the LLM returned an empty response")
            return
        self.history.append(Message.assistant(response))
        memory.add_assistant_message(response)
        self.printer(response)

    async def _chat_with_tools(self, max_tool_rounds: int = 4) -> str:
        if self.client is None:
            return ""
        schemas = self._chat_tool_schemas()
        toolbox = RefactorAgentToolbox(self.resolved_root)
        for _ in range(max_tool_rounds + 1):
            response = await self.client.chat(messages=self.history, tools=schemas)
            if not response.has_tool_calls():
                return response.content
            calls = response.tool_calls or []
            self.history.append(
                Message.assistant(response.content, response.reasoning_content, calls)
            )
            for call in calls:
                output = self._execute_chat_tool(toolbox, call.name, _safe_arguments(call.arguments))
                self.history.append(Message.tool(call.id, output))
                if self.memory:
                    self.memory.add_tool_result(call.name, output)
        return ""

    def _execute_chat_tool(self, toolbox: RefactorAgentToolbox, name: str, arguments: dict[str, Any]) -> str:
        try:
            if name == "read_file":
                payload: Any = toolbox.read_file_lines(
                    str(arguments.get("file_path", "")),
                    start_line=int(arguments.get("start_line", 1) or 1),
                    end_line=int(arguments["end_line"]) if arguments.get("end_line") is not None else None,
                )
                return json.dumps(payload, ensure_ascii=False)
            if name == "search_code":
                payload = toolbox.search_code(
                    str(arguments.get("query", "")), limit=int(arguments.get("limit", 20) or 20)
                )
                return json.dumps(payload, ensure_ascii=False)
            if name == "save_memory" and self.memory:
                fact = str(arguments.get("fact", "")).strip()
                if not fact:
                    return "保存长期记忆失败: fact 不能为空"
                scope = str(arguments.get("scope", "project"))
                entry = self.memory.store_fact(fact, scope)
                return f"已保存到长期记忆({self.active_long_term.scope_of(entry)}): {fact}"
            return f"unknown tool: {name}"
        except (OSError, TypeError, ValueError) as err:
            return f"tool failed: {err}"

    @staticmethod
    def _chat_tool_schemas() -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read a line-numbered repository file excerpt.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "file_path": {"type": "string"},
                            "start_line": {"type": "integer"},
                            "end_line": {"type": "integer"},
                        },
                        "required": ["file_path"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "search_code",
                    "description": "Search Java files for literal text.",
                    "parameters": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}},
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "save_memory",
                    "description": "Save a durable fact only when the user explicitly asks to remember it.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "fact": {"type": "string"},
                            "scope": {"type": "string", "enum": ["project", "global"]},
                        },
                        "required": ["fact"],
                    },
                },
            },
        ]

    def _handle_memory(self, argv: list[str]) -> None:
        action = argv[1].lower() if len(argv) > 1 else "status"
        if action == "status":
            if self.memory:
                self.printer(self.memory.status())
            else:
                self.printer(
                    f"长期记忆: {len(self.active_long_term.get_all())}条 / "
                    f"{self.active_long_term.token_count} tokens"
                )
            return
        if action == "list":
            self._print_memory_entries(self.active_long_term.get_all())
            return
        if action == "search":
            query = " ".join(argv[2:]).strip()
            self._print_memory_entries(self.active_long_term.search(query, 20, str(self.resolved_root)))
            return
        if action == "delete" and len(argv) > 2:
            deleted = self.active_long_term.delete(argv[2])
            self.printer(("Deleted: " if deleted else "Memory not found: ") + argv[2])
            return
        if action == "clear":
            self.active_long_term.clear()
            self.printer("Long-term memory cleared.")
            return
        self.printer("Usage: /memory [status|list|search QUERY|delete ID|clear]")

    def _handle_save(self, argv: list[str]) -> None:
        global_scope = "--global" in argv[1:]
        fact = " ".join(item for item in argv[1:] if item != "--global").strip()
        if not fact:
            self.printer("Usage: /save [--global] FACT")
            return
        project = str(self.resolved_root)
        metadata = {"source": "fact", "scope": "global" if global_scope else "project"}
        if not global_scope:
            metadata["project"] = project
        entry = MemoryEntry(
            id=f"fact-{uuid.uuid4().hex[:8]}", content=fact, type=MemoryType.FACT, metadata=metadata
        )
        self.active_long_term.store(entry)
        self.printer(f"Saved to long-term memory({'global' if global_scope else 'project'}): {fact}")

    def _handle_init(self, argv: list[str]) -> None:
        result = ProjectMemoryInitializer.initialize(self.resolved_root, force="--force" in argv[1:])
        if result.created:
            self.printer(f"Created {result.path}")
        elif result.overwritten:
            self.printer(f"Overwrote {result.path}")
        else:
            self.printer(f"Skipped existing {result.path}; use --force to overwrite")

    def _handle_compact(self) -> None:
        memory = self._ensure_memory()
        if memory is None:
            return
        compacted = bool(_run_async(memory.compact_history_now(self.history)))
        self.printer("Conversation history compacted." if compacted else "Not enough conversation history to compact.")

    def _print_memory_entries(self, entries: list[Any]) -> None:
        if not entries:
            self.printer("No matching long-term memory.")
            return
        for entry in entries:
            self.printer(f"{entry.id} [{self.active_long_term.scope_of(entry)}] {entry.content}")

    def _run_scan(self) -> None:
        exit_code = self.scan_handler(output_format="text")
        if exit_code == 0:
            self._select_first_issue_if_available()

    def _run_plan(self, argv: list[str]) -> None:
        issue_id = self._issue_or_selected(argv)
        if issue_id is None:
            return
        exit_code = self.plan_handler(issue_id=issue_id)
        if exit_code == 0:
            self.selected_issue_id = issue_id

    def _run_apply(self, argv: list[str]) -> None:
        issue_id = self._issue_or_selected(argv)
        if issue_id is None:
            return
        exit_code = self.apply_handler(
            issue_id=issue_id,
            assume_yes="--yes" in argv,
            max_repair_attempts=_repair_attempts(argv),
        )
        if exit_code == 0:
            self.selected_issue_id = issue_id

    def _run_characterize(self, argv: list[str]) -> None:
        issue_id = self._issue_or_selected(argv)
        if issue_id is None:
            return
        self.characterize_handler(issue_id=issue_id, assume_yes="--yes" in argv)

    def _run_rollback(self, argv: list[str]) -> None:
        self.rollback_handler(task_id=None, assume_yes="--yes" in argv)

    def _run_report(self) -> None:
        self.report_handler(task_id=None, latest=True)

    def _select_issue(self, argv: list[str]) -> None:
        issue_id = _issue_from_argv(argv)
        if issue_id is None:
            self.printer("Usage: select RA-0001")
            return
        self.selected_issue_id = issue_id
        self.printer(f"Selected issue: {issue_id}")

    def _list_issues(self) -> None:
        try:
            result = self.storage.load_scan_result()
        except FileNotFoundError:
            self.printer("No scan result found. Run scan first.")
            return
        if not result.issues:
            self.printer("No issues found in the latest scan.")
            return
        for issue in result.issues:
            self.printer(
                f"{issue.id} [{issue.severity}] {issue.type} "
                f"{issue.file_path}:{issue.start_line}-{issue.end_line} {issue.symbol or ''}".rstrip()
            )
        if self.selected_issue_id is None:
            self.selected_issue_id = result.issues[0].id
            self.printer(f"Selected issue: {self.selected_issue_id}")

    def _show_status(self) -> None:
        self.printer(f"Project root: {self.root}")
        self.printer(f"Selected issue: {self.selected_issue_id or 'none'}")
        latest_task = self.storage.latest_task_dir()
        self.printer(f"Latest task: {latest_task.name if latest_task else 'none'}")

    def _select_first_issue_if_available(self) -> None:
        try:
            result = self.storage.load_scan_result()
        except FileNotFoundError:
            return
        if result.issues:
            self.selected_issue_id = result.issues[0].id
            self.printer(f"Selected issue: {self.selected_issue_id}")

    def _issue_or_selected(self, argv: list[str]) -> IssueId:
        issue_id = _issue_from_argv(argv) or self.selected_issue_id
        if issue_id is None:
            self.printer("No issue selected. Use an issue id like RA-0001 or run scan/issues first.")
            return None
        return issue_id


def run_chat() -> int:
    return RefactorChatSession().run()


def _split_command(message: str) -> list[str]:
    try:
        return shlex.split(message.strip())
    except ValueError:
        return []


def _issue_from_argv(argv: list[str]) -> IssueId:
    for item in argv[1:]:
        match = ISSUE_RE.fullmatch(item)
        if match:
            return item.upper()
    return None


def _repair_attempts(argv: list[str]) -> int:
    if "--no-repair" in argv:
        return 0
    if "--max-repair-attempts" in argv:
        index = argv.index("--max-repair-attempts")
        if index + 1 < len(argv):
            try:
                return max(0, int(argv[index + 1]))
            except ValueError:
                return 2
    for item in argv[1:]:
        if item.startswith("--max-repair-attempts="):
            try:
                return max(0, int(item.split("=", 1)[1]))
            except ValueError:
                return 2
    return 2


def _safe_arguments(arguments: str) -> dict[str, Any]:
    try:
        value = json.loads(arguments or "{}")
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}
