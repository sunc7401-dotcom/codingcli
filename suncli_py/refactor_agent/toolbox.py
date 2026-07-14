"""Read-only tools exposed to the refactor-agent LLM decision loop."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from suncli_py.refactor_agent.java_ast import AstFileAnalysis
from suncli_py.refactor_agent.java_context import JavaContextCollector
from suncli_py.refactor_agent.models import RefactorIssue, RefactorPlan, VerificationResult

IGNORED_DIRS = {".git", ".paicli", "target", "build", ".gradle", "node_modules"}


class RefactorAgentToolbox:
    """Small read-only codebase toolbox used to build LLM context.

    The LLM makes decisions from these observations; this object never writes
    files and never applies patches.
    """

    def __init__(
        self,
        root: str | Path,
        ast_analyses: Sequence[AstFileAnalysis] | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self._ast_analyses = tuple(ast_analyses) if ast_analyses is not None else None

    def issue_context(self, issue: RefactorIssue) -> dict[str, Any]:
        context = JavaContextCollector(self.root, ast_analyses=self._ast_analyses).collect(issue)
        return {
            "issue": issue.to_dict(),
            "source_excerpt": context.source_excerpt,
            "related_tests": context.related_tests,
            "direct_callers": context.direct_callers,
            "warnings": context.warnings,
        }

    def issue_candidates(self, issues: list[RefactorIssue], *, limit: int = 20) -> dict[str, Any]:
        return {
            "candidate_count": len(issues),
            "candidates": [
                {
                    "issue": issue.to_dict(),
                    "context": self.issue_context(issue),
                }
                for issue in issues[:limit]
            ],
        }

    def plan_context(self, plan: RefactorPlan, issue: RefactorIssue) -> dict[str, Any]:
        return {
            "issue_context": self.issue_context(issue),
            "plan_scaffold": plan.to_dict(),
            "allowed_files": plan.files_to_modify,
            "java_files": self.list_java_files(limit=80),
        }

    def repair_context(
        self,
        plan: RefactorPlan,
        issue: RefactorIssue,
        verification: VerificationResult,
        *,
        attempt: int,
    ) -> dict[str, Any]:
        return {
            "attempt": attempt,
            "issue_context": self.issue_context(issue),
            "plan": plan.to_dict(),
            "allowed_files": plan.files_to_modify,
            "verification": verification.to_dict(),
            "current_file_excerpts": {
                file_path: self.read_file(file_path, max_chars=8000) for file_path in plan.files_to_modify[:5]
            },
        }

    def read_file(self, file_path: str, *, max_chars: int = 8000) -> str:
        path = self._resolve_repo_file(file_path)
        if path is None or not path.is_file():
            return ""
        return path.read_text(encoding="utf-8", errors="replace")[:max_chars]

    def read_file_lines(self, file_path: str, *, start_line: int = 1, end_line: int | None = None) -> dict[str, Any]:
        path = self._resolve_repo_file(file_path)
        if path is None or not path.is_file():
            return {"file_path": file_path, "content": "", "error": "file not found or not allowed"}
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        start = max(1, start_line)
        end = min(end_line or start + 120, len(lines))
        excerpt = [f"{number:>4}: {text}" for number, text in enumerate(lines[start - 1 : end], start=start)]
        return {
            "file_path": file_path,
            "start_line": start,
            "end_line": end,
            "content": "\n".join(excerpt),
        }

    def search_code(self, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
        query = query.strip()
        if not query:
            return []
        results: list[dict[str, Any]] = []
        pattern = re.compile(re.escape(query), re.IGNORECASE)
        for path in sorted(self.root.rglob("*.java")):
            relative = path.relative_to(self.root)
            if any(part in IGNORED_DIRS for part in relative.parts):
                continue
            for line_number, line in enumerate(
                path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
            ):
                if pattern.search(line):
                    results.append(
                        {
                            "file_path": relative.as_posix(),
                            "line": line_number,
                            "text": line.strip(),
                        }
                    )
                    if len(results) >= limit:
                        return results
        return results

    def list_java_files(self, *, limit: int = 100) -> list[str]:
        files: list[str] = []
        for path in sorted(self.root.rglob("*.java")):
            relative = path.relative_to(self.root)
            if any(part in IGNORED_DIRS for part in relative.parts):
                continue
            files.append(relative.as_posix())
            if len(files) >= limit:
                break
        return files

    def as_json(self, payload: dict[str, Any]) -> str:
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def _resolve_repo_file(self, file_path: str) -> Path | None:
        relative = Path(file_path.replace("\\", "/").lstrip("/"))
        if relative.is_absolute() or any(part in IGNORED_DIRS for part in relative.parts):
            return None
        path = (self.root / relative).resolve()
        try:
            path.relative_to(self.root)
        except ValueError:
            return None
        return path


class RefactorAgentToolRuntime:
    """OpenAI-style tool schema and executor for the LLM refactor loop."""

    def __init__(
        self,
        toolbox: RefactorAgentToolbox,
        *,
        issues: list[RefactorIssue] | None = None,
        plan: RefactorPlan | None = None,
        issue: RefactorIssue | None = None,
        verification: VerificationResult | None = None,
    ) -> None:
        self.toolbox = toolbox
        self.issues = issues or []
        self.plan = plan
        self.issue = issue
        self.verification = verification

    def schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "get_issue_context",
                    "description": (
                        "Return source excerpt, related tests, direct callers, and rule/AST evidence for an issue."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {"issue_id": {"type": "string"}},
                        "required": ["issue_id"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read a line-numbered excerpt from a repository file.",
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
                    "description": "Search Java files for a literal symbol or text snippet.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string"},
                            "limit": {"type": "integer"},
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_plan_context",
                    "description": "Return the current plan scaffold, allowed files, and target issue context.",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_verification_feedback",
                    "description": "Return compile/test/coverage feedback from the last verification run.",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                },
            },
        ]

    def execute(self, name: str, arguments: dict[str, Any]) -> str:
        try:
            if name == "get_issue_context":
                issue = self._find_issue(str(arguments.get("issue_id", "")))
                payload = self.toolbox.issue_context(issue) if issue else {"error": "issue not found"}
            elif name == "read_file":
                payload = self.toolbox.read_file_lines(
                    str(arguments.get("file_path", "")),
                    start_line=int(arguments.get("start_line", 1) or 1),
                    end_line=int(arguments["end_line"]) if arguments.get("end_line") is not None else None,
                )
            elif name == "search_code":
                payload = self.toolbox.search_code(
                    str(arguments.get("query", "")),
                    limit=int(arguments.get("limit", 20) or 20),
                )
            elif name == "get_plan_context" and self.plan and self.issue:
                payload = self.toolbox.plan_context(self.plan, self.issue)
            elif name == "get_verification_feedback" and self.verification:
                payload = self.verification.to_dict()
            else:
                payload = {"error": f"unknown or unavailable tool: {name}"}
        except Exception as err:
            payload = {"error": str(err), "tool": name}
        return json.dumps(payload, ensure_ascii=False)

    def _find_issue(self, issue_id: str) -> RefactorIssue | None:
        normalized = issue_id.strip().upper()
        if self.issue and self.issue.id.upper() == normalized:
            return self.issue
        for issue in self.issues:
            if issue.id.upper() == normalized:
                return issue
        return None
