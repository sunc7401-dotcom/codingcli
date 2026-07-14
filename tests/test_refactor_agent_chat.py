from __future__ import annotations

from pathlib import Path

from suncli_py.refactor_agent.core.models import (
    Evidence,
    ProjectProfile,
    RefactoringType,
    RefactorIssue,
    RiskLevel,
    ScanResult,
    Severity,
    SmellType,
)
from suncli_py.refactor_agent.core.storage import RefactorAgentStorage
from suncli_py.refactor_agent.interface.chat import RefactorChatSession
from suncli_py.refactor_agent.interface.cli import build_parser


def test_cli_registers_chat_command() -> None:
    args = build_parser().parse_args(["chat"])

    assert args.command == "chat"


def test_chat_routes_commands_and_keeps_selected_issue(tmp_path: Path) -> None:
    calls: list[tuple[str, dict]] = []
    outputs: list[str] = []
    storage = RefactorAgentStorage(tmp_path)

    def scan_handler(**kwargs) -> int:
        calls.append(("scan", kwargs))
        storage.save_scan_result(
            ScanResult(
                profile=ProjectProfile(
                    root=tmp_path,
                    is_git_repo=True,
                    is_maven_project=True,
                    has_main_java=True,
                    has_test_java=True,
                    is_git_clean=True,
                ),
                issues=[_issue()],
            )
        )
        return 0

    def plan_handler(**kwargs) -> int:
        calls.append(("plan", kwargs))
        return 0

    def apply_handler(**kwargs) -> int:
        calls.append(("apply", kwargs))
        return 0

    def verify_handler(**kwargs) -> int:
        calls.append(("verify", kwargs))
        return 0

    def rollback_handler(**kwargs) -> int:
        calls.append(("rollback", kwargs))
        return 0

    def report_handler(**kwargs) -> int:
        calls.append(("report", kwargs))
        return 0

    session = RefactorChatSession(
        root=tmp_path,
        scan_handler=scan_handler,
        plan_handler=plan_handler,
        apply_handler=apply_handler,
        verify_handler=verify_handler,
        rollback_handler=rollback_handler,
        report_handler=report_handler,
        printer=outputs.append,
    )

    assert session.handle_message("scan") is True
    assert session.selected_issue_id == "RA-0001"
    assert session.handle_message("plan") is True
    assert session.handle_message("apply --yes --max-repair-attempts 2") is True
    assert session.handle_message("verify") is True
    assert session.handle_message("report") is True
    assert session.handle_message("rollback --yes") is True

    assert calls == [
        ("scan", {"output_format": "text"}),
        ("plan", {"issue_id": "RA-0001"}),
        ("apply", {"issue_id": "RA-0001", "assume_yes": True, "max_repair_attempts": 2}),
        ("verify", {"issue_id": "RA-0001"}),
        ("report", {"task_id": None, "latest": True}),
        ("rollback", {"task_id": None, "assume_yes": True}),
    ]
    assert any("Selected issue: RA-0001" in output for output in outputs)


def test_chat_lists_issues_and_selects_first_issue(tmp_path: Path) -> None:
    outputs: list[str] = []
    RefactorAgentStorage(tmp_path).save_scan_result(
        ScanResult(
            profile=ProjectProfile(
                root=tmp_path,
                is_git_repo=True,
                is_maven_project=True,
                has_main_java=True,
                has_test_java=False,
                is_git_clean=True,
            ),
            issues=[_issue()],
        )
    )
    session = RefactorChatSession(root=tmp_path, printer=outputs.append)

    assert session.handle_message("issues") is True

    assert session.selected_issue_id == "RA-0001"
    assert any("RA-0001" in output for output in outputs)


def test_chat_rejects_natural_language_requests(tmp_path: Path) -> None:
    calls: list[tuple[str, dict]] = []
    outputs: list[str] = []
    session = RefactorChatSession(
        root=tmp_path,
        scan_handler=lambda **kwargs: calls.append(("scan", kwargs)) or 0,
        printer=outputs.append,
    )

    assert session.handle_message("扫描当前项目") is True

    assert calls == []
    assert outputs == ["Unknown command: 扫描当前项目. Type help for commands."]


def _issue() -> RefactorIssue:
    return RefactorIssue(
        id="RA-0001",
        type=SmellType.DEAD_CODE,
        severity=Severity.LOW,
        file_path="src/main/java/demo/OrderService.java",
        symbol="unusedPrivate",
        start_line=4,
        end_line=6,
        evidence=[Evidence("private method has no references")],
        impact="dead private code adds noise",
        recommendation="remove dead code",
        suggested_refactoring=RefactoringType.REMOVE_DEAD_CODE,
        risk_level=RiskLevel.LOW,
    )
