"""Standalone CLI entry point for Java refactor-agent."""

from __future__ import annotations

import argparse

from suncli_py.refactor_agent.interface.commands import (
    RefactorAgentError,
    run_apply,
    run_characterize,
    run_plan,
    run_report,
    run_rollback,
    run_scan,
    run_verify,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="refactor-agent", description="Java Maven safe refactoring agent")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_parser = subparsers.add_parser("scan", help="scan the current Java Maven Git project")
    scan_parser.add_argument("--format", choices=("text", "json"), default="text", help="output format")

    plan_parser = subparsers.add_parser("plan", help="generate an LLM-authored refactoring plan for an issue")
    plan_parser.add_argument("--issue", required=True, help="issue id, for example RA-0001")

    apply_parser = subparsers.add_parser("apply", help="apply the confirmed LLM edit plan")
    apply_parser.add_argument("--issue", required=True, help="issue id, for example RA-0001")
    apply_parser.add_argument("--yes", action="store_true", help="skip confirmation for low-risk tasks")
    apply_parser.add_argument(
        "--max-repair-attempts",
        type=int,
        default=1,
        help="verify after apply and ask the LLM to repair failed compile/test runs up to N times",
    )

    characterize_parser = subparsers.add_parser("characterize", help="generate candidate characterization test")
    characterize_parser.add_argument("--issue", required=True, help="issue id, for example RA-0001")
    characterize_parser.add_argument("--yes", action="store_true", help="write the candidate test without prompting")

    verify_parser = subparsers.add_parser("verify", help="run Maven verification and coverage awareness")
    verify_parser.add_argument("--issue", help="issue id; defaults to the latest task")

    rollback_parser = subparsers.add_parser("rollback", help="restore planned files from the task snapshot")
    rollback_parser.add_argument("--task", help="task id; defaults to the latest task")
    rollback_parser.add_argument("--yes", action="store_true", help="confirm restore when conflicts are detected")

    report_parser = subparsers.add_parser("report", help="show refactor-agent report")
    report_parser.add_argument("--task", help="task id; defaults to the latest task")
    report_parser.add_argument("--latest", action="store_true", help="show reports/latest.md")

    subparsers.add_parser("chat", help="start an interactive refactor-agent chat session")

    memory_parser = subparsers.add_parser("memory", help="inspect or manage Python long-term memory")
    memory_subparsers = memory_parser.add_subparsers(dest="memory_action", required=True)
    memory_subparsers.add_parser("status", help="show memory counts and token estimate")
    memory_subparsers.add_parser("list", help="list all stored memories")
    memory_search = memory_subparsers.add_parser("search", help="search current-project and global memories")
    memory_search.add_argument("query", help="search query")
    memory_delete = memory_subparsers.add_parser("delete", help="delete one memory by id")
    memory_delete.add_argument("id", help="memory id")
    memory_subparsers.add_parser("clear", help="clear all Python long-term memory")

    save_parser = subparsers.add_parser("save", help="explicitly save a durable fact")
    save_parser.add_argument("fact", nargs="+", help="fact or preference to remember")
    save_parser.add_argument(
        "--global", dest="global_scope", action="store_true", help="make it visible in all projects"
    )

    init_parser = subparsers.add_parser("init", help="create a concise PAI.md in the current project")
    init_parser.add_argument("--force", action="store_true", help="overwrite an existing PAI.md")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    try:
        if args.command == "scan":
            raise SystemExit(run_scan(output_format=args.format))
        if args.command == "plan":
            raise SystemExit(run_plan(issue_id=args.issue))
        if args.command == "apply":
            raise SystemExit(
                run_apply(
                    issue_id=args.issue,
                    assume_yes=args.yes,
                    max_repair_attempts=max(0, args.max_repair_attempts),
                )
            )
        if args.command == "characterize":
            raise SystemExit(run_characterize(issue_id=args.issue, assume_yes=args.yes))
        if args.command == "verify":
            raise SystemExit(run_verify(issue_id=args.issue))
        if args.command == "rollback":
            raise SystemExit(run_rollback(task_id=args.task, assume_yes=args.yes))
        if args.command == "report":
            raise SystemExit(run_report(task_id=args.task, latest=args.latest))
        if args.command == "chat":
            from suncli_py.refactor_agent.interface.chat import run_chat

            raise SystemExit(run_chat())
        if args.command == "memory":
            from suncli_py.memory.commands import run_memory

            value = getattr(args, "query", None) or getattr(args, "id", None)
            raise SystemExit(run_memory(args.memory_action, value))
        if args.command == "save":
            from suncli_py.memory.commands import run_save

            raise SystemExit(run_save(" ".join(args.fact), global_scope=args.global_scope))
        if args.command == "init":
            from suncli_py.memory.commands import run_init

            raise SystemExit(run_init(force=args.force))
    except RefactorAgentError as err:
        parser.exit(2, f"error: {err}\n")


if __name__ == "__main__":
    main()
