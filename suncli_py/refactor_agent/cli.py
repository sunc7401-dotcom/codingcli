"""Standalone CLI entry point for Java refactor-agent."""

from __future__ import annotations

import argparse

from suncli_py.refactor_agent.commands import RefactorAgentError, run_scan


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="refactor-agent", description="Java Maven 安全重构 CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_parser = subparsers.add_parser("scan", help="检测当前 Java Maven Git 项目")
    scan_parser.add_argument("--format", choices=("text", "json"), default="text", help="输出格式")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    try:
        if args.command == "scan":
            raise SystemExit(run_scan(output_format=args.format))
    except RefactorAgentError as err:
        parser.exit(2, f"错误: {err}\n")


if __name__ == "__main__":
    main()
