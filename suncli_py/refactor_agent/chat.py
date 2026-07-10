"""Command-only interactive shell for the Java refactor-agent."""

from __future__ import annotations

import re
import shlex
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from suncli_py.refactor_agent.commands import (
    RefactorAgentError,
    run_apply,
    run_characterize,
    run_plan,
    run_report,
    run_rollback,
    run_scan,
    run_verify,
)
from suncli_py.refactor_agent.storage import RefactorAgentStorage

IssueId = str | None
Printer = Callable[[str], None]

ISSUE_RE = re.compile(r"\bRA-\d{4,}\b", re.IGNORECASE)


HELP_TEXT = """Commands:
  scan
  issues
  select RA-0001
  plan RA-0001
  apply RA-0001
  apply RA-0001 --yes --max-repair-attempts 1
  verify RA-0001
  characterize RA-0001
  characterize RA-0001 --yes
  report
  rollback
  rollback --yes
  status
  help
  exit
""".strip()


@dataclass
class RefactorChatSession:
    root: Path | str = "."
    scan_handler: Callable[..., int] = run_scan
    plan_handler: Callable[..., int] = run_plan
    apply_handler: Callable[..., int] = run_apply
    verify_handler: Callable[..., int] = run_verify
    characterize_handler: Callable[..., int] = run_characterize
    rollback_handler: Callable[..., int] = run_rollback
    report_handler: Callable[..., int] = run_report
    printer: Printer = print
    selected_issue_id: IssueId = None

    def __post_init__(self) -> None:
        self.root = Path(self.root).resolve()
        self.storage = RefactorAgentStorage(self.root)

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
                self._run_verify(argv)
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

        self.printer(f"Unknown command: {argv[0]}. Type help for commands.")
        return True

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

    def _run_verify(self, argv: list[str]) -> None:
        issue_id = _issue_from_argv(argv) or self.selected_issue_id
        exit_code = self.verify_handler(issue_id=issue_id)
        if exit_code == 0 and issue_id:
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
                return 1
    for item in argv[1:]:
        if item.startswith("--max-repair-attempts="):
            try:
                return max(0, int(item.split("=", 1)[1]))
            except ValueError:
                return 1
    return 1
