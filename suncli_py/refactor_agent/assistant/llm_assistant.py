"""LLM decision, planning, and controlled edit generation for refactor-agent."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from loguru import logger

from suncli_py.config.config import PaiCliConfig
from suncli_py.llm.client import LlmClient
from suncli_py.llm.factory import create_client_from_config
from suncli_py.llm.models import Message, ToolCall
from suncli_py.refactor_agent.analysis.java_ast import AstFileAnalysis
from suncli_py.refactor_agent.assistant.prompts import (
    edit_system_prompt,
    explanation_system_prompt,
    planning_system_prompt,
    repair_system_prompt,
    triage_system_prompt,
)
from suncli_py.refactor_agent.assistant.toolbox import RefactorAgentToolbox, RefactorAgentToolRuntime
from suncli_py.refactor_agent.core.models import (
    CandidateDecision,
    DecisionStatus,
    Evidence,
    RefactoringType,
    RefactorIssue,
    RefactorPlan,
    RiskLevel,
    Severity,
    TriageResult,
    VerificationResult,
)


class RefactorLlmAssistant:
    """LLM brain for the Java refactor agent.

    Static rules, JavaParser AST data, Symbol Solver calls, tests, and file
    excerpts are treated as tool observations. The LLM decides priority,
    planning, patch operations, and repair attempts; the rest of the pipeline
    validates and applies those decisions.
    """

    def __init__(self, client: LlmClient) -> None:
        self.client = client
        self._scan_ast_analyses: tuple[AstFileAnalysis, ...] | None = None

    def bind_scan_analyses(self, analyses: Sequence[AstFileAnalysis]) -> None:
        """Reuse the AST snapshot produced by the current scan."""
        self._scan_ast_analyses = tuple(analyses)

    @classmethod
    def from_config(cls) -> RefactorLlmAssistant | None:
        client = create_client_from_config(PaiCliConfig.load())
        return cls(client) if client else None

    def triage_issues(self, root: Path, issues: list[RefactorIssue], *, limit: int = 20) -> TriageResult:
        """Investigate candidates individually and accept, reject, or defer them."""
        if not issues:
            return TriageResult(issues=[], decisions=[])

        toolbox = RefactorAgentToolbox(root, self._scan_ast_analyses)
        tools = RefactorAgentToolRuntime(toolbox, issues=issues)
        decisions: list[CandidateDecision] = []
        ranked: list[tuple[int, RefactorIssue]] = []
        for index, issue in enumerate(issues):
            if index >= limit:
                decisions.append(
                    CandidateDecision(
                        candidate_id=issue.id,
                        status=DecisionStatus.UNCERTAIN,
                        confidence=0.0,
                        reason=f"Candidate was not investigated because the scan limit is {limit}.",
                    )
                )
                continue

            data = self._chat_json(
                system=triage_system_prompt(),
                user=(
                    "Investigate this single scanner candidate and make the final semantic decision. Return JSON: "
                    '{"candidate_id":"RA-0001","decision":"accept|reject|uncertain",'
                    '"confidence":0.0,"priority":1,"reason":"...","root_cause":"...",'
                    '"source_evidence":[{"file_path":"...","start_line":1,"end_line":2,"reason":"..."}],'
                    '"severity":"low|medium|high","risk_level":"low|medium|high",'
                    '"suggested_refactoring":"Extract Method|Extract Class|Introduce Explaining Variable|'
                    'Move Method|Replace Duplicate Logic With Shared Method|Remove Dead Code|'
                    'Rename Variable / Method / Class",'
                    '"impact":"...","recommendation":"...","proposed_solution":"...",'
                    '"verification_strategy":["..."]}. '
                    "Do not accept a candidate without concrete source_evidence.\n"
                    + toolbox.as_json(toolbox.issue_context(issue))
                ),
                tools=tools,
            )
            decision = _candidate_decision(root, issue, data)
            decisions.append(decision)
            if decision.status != DecisionStatus.ACCEPT:
                continue

            priority = _int_value(data.get("priority"), index + 1)
            ranked.append(
                (
                    priority,
                    replace(
                        issue,
                        severity=_enum_value(Severity, data.get("severity"), issue.severity),
                        risk_level=_enum_value(RiskLevel, data.get("risk_level"), issue.risk_level),
                        suggested_refactoring=_enum_value(
                            RefactoringType, data.get("suggested_refactoring"), issue.suggested_refactoring
                        ),
                        impact=str(data.get("impact") or issue.impact),
                        recommendation=str(
                            data.get("recommendation") or decision.proposed_solution or issue.recommendation
                        ),
                        evidence=[
                            *issue.evidence,
                            Evidence(
                                "LLM triage decision",
                                {
                                    "decision": decision.status.value,
                                    "confidence": decision.confidence,
                                    "priority": priority,
                                    "reason": decision.reason,
                                    "root_cause": decision.root_cause,
                                    "source_evidence": decision.source_evidence,
                                    "verification_strategy": decision.verification_strategy,
                                },
                            ),
                        ],
                    ),
                )
            )
        return TriageResult(
            issues=[issue for _, issue in sorted(ranked, key=lambda item: item[0])],
            decisions=decisions,
        )

    def _legacy_triage_issues(self, root: Path, issues: list[RefactorIssue], *, limit: int = 20) -> list[RefactorIssue]:
        """Let the LLM decide which rule/AST candidates are worth fixing."""
        if not issues:
            return []

        toolbox = RefactorAgentToolbox(root)
        tools = RefactorAgentToolRuntime(toolbox, issues=issues)
        data = self._chat_json(
            system=triage_system_prompt(),
            user=(
                "Triage these candidate code issues. Return JSON: "
                '{"issues":[{"id":"RA-0001","priority":1,'
                '"severity":"low|medium|high","risk_level":"low|medium|high",'
                '"suggested_refactoring":"Extract Method|Extract Class|Introduce Explaining Variable|'
                'Move Method|Replace Duplicate Logic With Shared Method|Remove Dead Code|'
                'Rename Variable / Method / Class",'
                '"impact":"...","recommendation":"...","decision_reason":"..."}]}.\n'
                + toolbox.as_json(toolbox.issue_candidates(issues, limit=limit))
            ),
            tools=tools,
        )

        decisions = {
            str(item.get("id", "")).upper(): item
            for item in data.get("issues", [])
            if isinstance(item, dict) and item.get("id")
        }
        ranked: list[tuple[int, RefactorIssue]] = []
        for index, issue in enumerate(issues):
            decision = decisions.get(issue.id.upper())
            if not decision:
                ranked.append((index + 10_000, issue))
                continue

            priority = _int_value(decision.get("priority"), index + 1)
            ranked.append(
                (
                    priority,
                    replace(
                        issue,
                        severity=_enum_value(Severity, decision.get("severity"), issue.severity),
                        risk_level=_enum_value(RiskLevel, decision.get("risk_level"), issue.risk_level),
                        suggested_refactoring=_enum_value(
                            RefactoringType,
                            decision.get("suggested_refactoring"),
                            issue.suggested_refactoring,
                        ),
                        impact=str(decision.get("impact") or issue.impact),
                        recommendation=str(decision.get("recommendation") or issue.recommendation),
                        evidence=[
                            *issue.evidence,
                            Evidence(
                                "LLM triage decision",
                                {
                                    "priority": priority,
                                    "reason": str(decision.get("decision_reason") or "").strip(),
                                },
                            ),
                        ],
                    ),
                )
            )
        return [issue for _, issue in sorted(ranked, key=lambda item: item[0])]

    def explain_issues(self, root: Path, issues: list[RefactorIssue], *, limit: int = 5) -> list[RefactorIssue]:
        """Backward-compatible issue explanation step."""
        updated: list[RefactorIssue] = []
        toolbox = RefactorAgentToolbox(root)
        for index, issue in enumerate(issues):
            if index >= limit:
                updated.append(issue)
                continue
            data = self._chat_json(
                system=explanation_system_prompt(),
                user=(
                    "Explain this Java issue and give a safe refactoring recommendation. Return JSON: "
                    '{"impact":"...","recommendation":"...","risk_notes":["..."],"confidence":"low|medium|high"}.\n'
                    + toolbox.as_json(toolbox.issue_context(issue))
                ),
                tools=RefactorAgentToolRuntime(toolbox, issue=issue),
            )
            risk_notes = [str(item) for item in data.get("risk_notes", []) if str(item).strip()]
            evidence = issue.evidence
            if risk_notes:
                evidence = [*issue.evidence, Evidence("LLM risk notes", {"notes": risk_notes})]
            updated.append(
                replace(
                    issue,
                    impact=str(data.get("impact") or issue.impact),
                    recommendation=str(data.get("recommendation") or issue.recommendation),
                    evidence=evidence,
                )
            )
        return updated

    def generate_plan(self, root: Path, plan: RefactorPlan, issue: RefactorIssue) -> RefactorPlan:
        """Let the LLM generate the user-confirmed plan from a safe scaffold."""
        toolbox = RefactorAgentToolbox(root)
        tools = RefactorAgentToolRuntime(toolbox, plan=plan, issue=issue)
        data = self._chat_json(
            system=planning_system_prompt(),
            user=(
                "Generate the refactoring plan. Return JSON: "
                '{"goal":"...","refactoring_type":"...","files_to_modify":["..."],'
                '"expected_changes":["..."],"out_of_scope":["..."],'
                '"risk_level":"low|medium|high","risk_reasons":["..."],'
                '"verification_commands":["..."],"rollback_strategy":"..."}.\n'
                + toolbox.as_json(toolbox.plan_context(plan, issue))
            ),
            tools=tools,
        )
        return replace(
            plan,
            goal=str(data.get("goal") or plan.goal),
            refactoring_type=_enum_value(RefactoringType, data.get("refactoring_type"), plan.refactoring_type),
            files_to_modify=_string_list(data.get("files_to_modify"), plan.files_to_modify),
            expected_changes=_string_list(data.get("expected_changes"), plan.expected_changes),
            out_of_scope=_string_list(data.get("out_of_scope"), plan.out_of_scope),
            risk_level=_enum_value(RiskLevel, data.get("risk_level"), plan.risk_level),
            risk_reasons=_string_list(data.get("risk_reasons"), plan.risk_reasons),
            verification_commands=_string_list(data.get("verification_commands"), plan.verification_commands),
            rollback_strategy=str(data.get("rollback_strategy") or plan.rollback_strategy),
            planning_source="llm-primary",
        )

    def enhance_plan(self, plan: RefactorPlan, issue: RefactorIssue) -> RefactorPlan:
        """Backward-compatible plan enhancement API used by older tests/callers."""
        payload = {
            "issue": issue.to_dict(),
            "plan": plan.to_dict(),
            "source_excerpt": plan.context.source_excerpt[:8000],
        }
        data = self._chat_json(
            system=planning_system_prompt(),
            user=(
                "Enhance this plan. Return JSON: "
                '{"goal":"...","expected_changes":["..."],"out_of_scope":["..."],'
                '"risk_reasons":["..."],"verification_commands":["..."]}.\n'
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
        toolbox = RefactorAgentToolbox(Path(".").resolve())
        tools = RefactorAgentToolRuntime(toolbox, plan=plan, issue=issue)
        payload = {
            "issue": issue.to_dict(),
            "plan": plan.to_dict(),
            "allowed_files": plan.files_to_modify,
            "source_excerpt": plan.context.source_excerpt[:10000],
        }
        data = self._chat_json(
            system=edit_system_prompt(),
            user=(
                "Generate the patch for this confirmed plan. Only modify allowed_files. Return JSON: "
                '{"edits":[{"file_path":"...","start_line":1,"end_line":1,"replacement":"..."}],'
                '"explanation":"...","risk_notes":["..."],"verification_focus":["..."]}. '
                'If more context is needed, return {"edits":[]}.\n'
                + json.dumps(payload, ensure_ascii=False)
            ),
            tools=tools,
        )
        return data if isinstance(data.get("edits"), list) and data.get("edits") else None

    def generate_repair_edit_plan(
        self,
        root: Path,
        plan: RefactorPlan,
        issue: RefactorIssue,
        verification: VerificationResult,
        *,
        attempt: int,
    ) -> dict[str, Any] | None:
        toolbox = RefactorAgentToolbox(root)
        tools = RefactorAgentToolRuntime(toolbox, plan=plan, issue=issue, verification=verification)
        data = self._chat_json(
            system=repair_system_prompt(),
            user=(
                "Generate a revised patch. Only edit allowed_files. Return JSON: "
                '{"edits":[{"file_path":"...","start_line":1,"end_line":1,"replacement":"..."}],'
                '"explanation":"...","verification_focus":["..."]}. '
                'If the failure cannot be repaired safely, return {"edits":[]}.\n'
                + toolbox.as_json(toolbox.repair_context(plan, issue, verification, attempt=attempt))
            ),
            tools=tools,
        )
        return data if isinstance(data.get("edits"), list) and data.get("edits") else None

    def _chat_json(
        self,
        *,
        system: str,
        user: str,
        tools: RefactorAgentToolRuntime | None = None,
        max_tool_rounds: int = 4,
    ) -> dict[str, Any]:
        messages = [Message.system(system), Message.user(user)]
        schemas = tools.schemas() if tools is not None else None
        for _ in range(max_tool_rounds + 1):
            try:
                response = _run_async(self.client.chat(messages=messages, tools=schemas))
            except (OSError, RuntimeError) as err:
                raise RefactorLlmError(f"LLM request failed: {err}") from err
            if not response:
                return {}
            if response.has_tool_calls() and tools is not None:
                tool_calls = response.tool_calls or []
                messages.append(
                    Message.assistant(
                        content=response.content,
                        reasoning_content=response.reasoning_content,
                        tool_calls=tool_calls,
                    )
                )
                tool_outputs = _run_async(_execute_tool_calls(tools, tool_calls))
                for tool_call, output in zip(tool_calls, tool_outputs, strict=True):
                    messages.append(
                        Message.tool(
                            tool_call.id,
                            output,
                        )
                    )
                continue
            return _parse_json_object(response.content)
        return {}


class RefactorLlmError(Exception):
    """Raised when the LLM provider call fails."""


async def _execute_tool_calls(tools: RefactorAgentToolRuntime, tool_calls: list[ToolCall]) -> list[str]:
    """Execute one model-planned tool batch concurrently while preserving result order."""
    if not tool_calls:
        return []

    count = len(tool_calls)
    logger.info("LLM requested {} tool(s)", count)
    if count > 1:
        logger.info("Executing {} independent tools in parallel", count)
    started = time.monotonic()
    outputs = await asyncio.gather(
        *[
            asyncio.to_thread(
                tools.execute,
                tool_call.name,
                _safe_tool_arguments(tool_call.arguments),
            )
            for tool_call in tool_calls
        ]
    )
    logger.info("Completed {} tool(s) in {:.0f} ms", count, (time.monotonic() - started) * 1000)
    return list(outputs)


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


def _safe_tool_arguments(arguments: str) -> dict[str, Any]:
    try:
        data = json.loads(arguments or "{}")
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _string_list(value: Any, fallback: list[str]) -> list[str]:
    if not isinstance(value, list):
        return fallback
    result = [str(item).strip() for item in value if str(item).strip()]
    return result or fallback


def _enum_value(enum_type, value: Any, fallback):
    if value is None:
        return fallback
    text = str(value).strip()
    if not text:
        return fallback
    for item in enum_type:
        if text.lower() in {item.value.lower(), item.name.lower()}:
            return item
    return fallback


def _int_value(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _candidate_decision(root: Path, issue: RefactorIssue, data: dict[str, Any]) -> CandidateDecision:
    status = _enum_value(DecisionStatus, data.get("decision"), DecisionStatus.UNCERTAIN)
    reason = str(data.get("reason") or "").strip()
    raw_evidence = data.get("source_evidence")
    source_evidence = _validated_source_evidence(root, raw_evidence)
    if status in {DecisionStatus.ACCEPT, DecisionStatus.REJECT} and (not reason or not source_evidence):
        status = DecisionStatus.UNCERTAIN
        reason = reason or "The model did not provide enough repository evidence for a final decision."
    try:
        confidence = min(1.0, max(0.0, float(data.get("confidence", 0.0))))
    except (TypeError, ValueError):
        confidence = 0.0
    return CandidateDecision(
        candidate_id=issue.id,
        status=status,
        confidence=confidence,
        reason=reason or "The model returned no supported decision.",
        source_evidence=source_evidence,
        root_cause=str(data.get("root_cause") or "").strip(),
        proposed_solution=str(data.get("proposed_solution") or data.get("recommendation") or "").strip(),
        verification_strategy=[
            str(item).strip()
            for item in data.get("verification_strategy", [])
            if str(item).strip()
        ]
        if isinstance(data.get("verification_strategy"), list)
        else [],
    )


def _validated_source_evidence(root: Path, value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    validated: list[dict[str, Any]] = []
    resolved_root = root.resolve()
    for item in value:
        if not isinstance(item, dict):
            continue
        file_path = str(item.get("file_path") or "").replace("\\", "/").lstrip("/")
        try:
            path = (resolved_root / file_path).resolve()
            path.relative_to(resolved_root)
            start_line = int(item.get("start_line", 0))
            end_line = int(item.get("end_line", start_line))
        except (OSError, TypeError, ValueError):
            continue
        if not path.is_file() or start_line < 1 or end_line < start_line:
            continue
        line_count = len(path.read_text(encoding="utf-8", errors="replace").splitlines())
        if end_line > line_count:
            continue
        validated.append(
            {
                "file_path": file_path,
                "start_line": start_line,
                "end_line": end_line,
                "reason": str(item.get("reason") or "").strip(),
            }
        )
    return validated
