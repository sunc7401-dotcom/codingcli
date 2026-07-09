"""LLM-assisted explanation, planning, and controlled edit generation."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from suncli_py.config.config import PaiCliConfig
from suncli_py.llm.client import LlmClient
from suncli_py.llm.factory import create_client_from_config
from suncli_py.llm.models import Message
from suncli_py.refactor_agent.java_context import JavaContextCollector
from suncli_py.refactor_agent.models import RefactorIssue, RefactorPlan


class RefactorLlmAssistant:
    def __init__(self, client: LlmClient) -> None:
        self.client = client

    @classmethod
    def from_config(cls) -> RefactorLlmAssistant | None:
        client = create_client_from_config(PaiCliConfig.load())
        return cls(client) if client else None

    def explain_issues(self, root: Path, issues: list[RefactorIssue], *, limit: int = 5) -> list[RefactorIssue]:
        updated: list[RefactorIssue] = []
        collector = JavaContextCollector(root)
        for index, issue in enumerate(issues):
            if index >= limit:
                updated.append(issue)
                continue
            context = collector.collect(issue)
            payload = {
                "issue": issue.to_dict(),
                "source_excerpt": context.source_excerpt[:6000],
                "related_tests": context.related_tests,
                "direct_callers": context.direct_callers,
            }
            data = self._chat_json(
                system="你是 Java 代码审查与安全重构 Agent，只输出 JSON。",
                user=(
                    "请解释这个 Java 坏味道，并给出安全重构建议。"
                    "输出 JSON: {\"impact\":\"...\",\"recommendation\":\"...\","
                    "\"risk_notes\":[\"...\"],\"confidence\":\"low|medium|high\"}。\n"
                    + json.dumps(payload, ensure_ascii=False)
                ),
            )
            impact = str(data.get("impact") or issue.impact)
            recommendation = str(data.get("recommendation") or issue.recommendation)
            risk_notes = [str(item) for item in data.get("risk_notes", []) if str(item).strip()]
            evidence = issue.evidence
            if risk_notes:
                from suncli_py.refactor_agent.models import Evidence

                evidence = [*issue.evidence, Evidence("LLM risk notes", {"notes": risk_notes})]
            updated.append(replace(issue, impact=impact, recommendation=recommendation, evidence=evidence))
        return updated

    def enhance_plan(self, plan: RefactorPlan, issue: RefactorIssue) -> RefactorPlan:
        payload = {
            "issue": issue.to_dict(),
            "plan": plan.to_dict(),
            "source_excerpt": plan.context.source_excerpt[:8000],
        }
        data = self._chat_json(
            system="你是 Java 安全重构规划 Agent，只输出 JSON，不要生成代码。",
            user=(
                "请基于 AST 上下文增强这个重构计划。"
                "输出 JSON: {\"goal\":\"...\",\"expected_changes\":[...],"
                "\"out_of_scope\":[...],\"risk_reasons\":[...],"
                "\"verification_commands\":[...]}。\n"
                + json.dumps(payload, ensure_ascii=False)
            ),
        )
        return replace(
            plan,
            goal=str(data.get("goal") or plan.goal),
            expected_changes=_string_list(data.get("expected_changes"), plan.expected_changes),
            out_of_scope=_string_list(data.get("out_of_scope"), plan.out_of_scope),
            risk_reasons=_string_list(data.get("risk_reasons"), plan.risk_reasons),
            verification_commands=_string_list(data.get("verification_commands"), plan.verification_commands),
            planning_source="llm-enhanced",
        )

    def generate_edit_plan(self, plan: RefactorPlan, issue: RefactorIssue) -> dict[str, Any] | None:
        payload = {
            "issue": issue.to_dict(),
            "plan": plan.to_dict(),
            "allowed_files": plan.files_to_modify,
            "source_excerpt": plan.context.source_excerpt[:10000],
        }
        data = self._chat_json(
            system="你是 Java patch 生成 Agent，只输出 JSON edit operations，不要输出 Markdown。",
            user=(
                "请为这个小步重构生成受控 edit operations。"
                "只能修改 allowed_files。输出 JSON: "
                "{\"edits\":[{\"file_path\":\"...\",\"start_line\":1,"
                "\"end_line\":1,\"replacement\":\"...\"}],"
                "\"explanation\":\"...\"}。如果信息不足，输出 {\"edits\":[]}。\n"
                + json.dumps(payload, ensure_ascii=False)
            ),
        )
        return data if isinstance(data.get("edits"), list) and data.get("edits") else None

    def _chat_json(self, *, system: str, user: str) -> dict[str, Any]:
        messages = [Message.system(system), Message.user(user)]
        response = _run_async(self.client.chat(messages=messages, tools=None))
        return _parse_json_object(response.content if response else "")


def _run_async(coro: Any) -> Any:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    return loop.run_until_complete(coro)


def _parse_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start < 0 or end < start:
        return {}
    try:
        data = json.loads(stripped[start : end + 1])
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _string_list(value: Any, fallback: list[str]) -> list[str]:
    if not isinstance(value, list):
        return fallback
    result = [str(item).strip() for item in value if str(item).strip()]
    return result or fallback
