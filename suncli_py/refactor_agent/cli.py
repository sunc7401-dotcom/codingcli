"""Standalone CLI entry point for Java refactor-agent."""

from __future__ import annotations

import argparse

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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="refactor-agent", description="Java Maven 安全重构 CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_parser = subparsers.add_parser("scan", help="检测当前 Java Maven Git 项目")
    scan_parser.add_argument("--format", choices=("text", "json"), default="text", help="输出格式")

    plan_parser = subparsers.add_parser("plan", help="为指定 issue 生成小步重构计划")
    plan_parser.add_argument("--issue", required=True, help="issue id，例如 RA-0001")

    apply_parser = subparsers.add_parser("apply", help="确认后应用指定 issue 的低风险重构 patch")
    apply_parser.add_argument("--issue", required=True, help="issue id，例如 RA-0001")
    apply_parser.add_argument("--yes", action="store_true", help="对低风险任务跳过交互确认")

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
            raise SystemExit(run_apply(issue_id=args.issue, assume_yes=args.yes))
        if args.command == "characterize":
            raise SystemExit(run_characterize(issue_id=args.issue, assume_yes=args.yes))
        if args.command == "verify":
            raise SystemExit(run_verify(issue_id=args.issue))
        if args.command == "rollback":
            raise SystemExit(run_rollback(task_id=args.task, assume_yes=args.yes))
        if args.command == "report":
            raise SystemExit(run_report(task_id=args.task, latest=args.latest))
    except RefactorAgentError as err:
        parser.exit(2, f"错误: {err}\n")


if __name__ == "__main__":
    main()
