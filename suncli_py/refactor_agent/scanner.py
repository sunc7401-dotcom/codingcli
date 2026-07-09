"""Local Java bad-smell scanner for the phase-two MVP."""

from __future__ import annotations

import re
import shutil
import subprocess
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from suncli_py.refactor_agent.java_ast import (
    AstFieldAccess,
    AstFileAnalysis,
    AstMethodCall,
    JavaAstError,
    JavaParserAnalyzer,
)
from suncli_py.refactor_agent.models import (
    Evidence,
    RefactoringType,
    RefactorIssue,
    RiskLevel,
    Severity,
    SmellType,
)
from suncli_py.refactor_agent.project_detector import CommandRunner

IGNORED_DIRS = {".git", ".paicli", "target", "build", ".gradle", "node_modules"}
UNCLEAR_LOCAL_NAMES = {"tmp", "temp", "data", "obj", "x", "y", "z", "foo", "bar"}
UNCLEAR_METHOD_NAMES = {"handle", "process", "doIt", "doit", "run", "execute"}
UNCLEAR_CLASS_SUFFIXES = ("Manager", "Helper", "Util")


@dataclass(frozen=True)
class JavaMethod:
    name: str
    start_line: int
    end_line: int
    body_lines: list[str]
    signature: str
    declaring_type: str
    resolved_signature: str
    symbol_resolved: bool
    is_private: bool
    is_static: bool
    method_calls: list[AstMethodCall]
    field_accesses: list[AstFieldAccess]


@dataclass(frozen=True)
class JavaClass:
    name: str
    start_line: int
    end_line: int
    body_lines: list[str]
    kind: str


@dataclass(frozen=True)
class JavaFileAnalysis:
    path: Path
    relative_path: str
    lines: list[str]
    sanitized_lines: list[str]
    methods: list[JavaMethod]
    classes: list[JavaClass]


def _default_command_runner(command: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    executable = shutil.which(command[0]) or command[0]
    return subprocess.run(
        [executable, *command[1:]],
        cwd=str(cwd),
        capture_output=True,
        check=False,
        encoding="utf-8",
        errors="replace",
        text=True,
        timeout=90,
    )


class JavaSmellScanner:
    """Scan Java source files with deterministic local heuristics."""

    def __init__(
        self,
        root: str | Path,
        command_runner: CommandRunner | None = None,
        ast_command_runner: CommandRunner | None = None,
        use_javaparser: bool = True,
    ) -> None:
        self.root = Path(root).resolve()
        self._run = command_runner or _default_command_runner
        self._ast_analyzer = JavaParserAnalyzer(self.root, ast_command_runner) if use_javaparser else None
        self.warnings: list[str] = []

    def scan(self) -> list[RefactorIssue]:
        self.warnings = []
        java_files = self._collect_java_files()
        analyses = self._analyze_files(java_files)
        issues: list[RefactorIssue] = []

        issues.extend(self._scan_long_methods(analyses))
        issues.extend(self._scan_large_classes(analyses))
        issues.extend(self._scan_complex_conditions(analyses))
        issues.extend(self._scan_unclear_naming(analyses))
        issues.extend(self._scan_dead_code(analyses))
        issues.extend(self._scan_feature_envy(analyses))
        issues.extend(self._scan_duplicate_code(analyses))

        sorted_issues = sorted(issues, key=lambda issue: (issue.file_path, issue.start_line, issue.type.value))
        return [
            RefactorIssue(
                id=f"RA-{index:04d}",
                type=issue.type,
                severity=issue.severity,
                file_path=issue.file_path,
                symbol=issue.symbol,
                start_line=issue.start_line,
                end_line=issue.end_line,
                evidence=issue.evidence,
                impact=issue.impact,
                recommendation=issue.recommendation,
                suggested_refactoring=issue.suggested_refactoring,
                auto_applicable=issue.auto_applicable,
                risk_level=issue.risk_level,
                requires_review=issue.requires_review,
            )
            for index, issue in enumerate(sorted_issues, start=1)
        ]

    def _collect_java_files(self) -> list[Path]:
        files: list[Path] = []
        for path in self.root.rglob("*.java"):
            if any(part in IGNORED_DIRS for part in path.relative_to(self.root).parts):
                continue
            files.append(path)
        return sorted(files)

    def _analyze_file(self, path: Path) -> JavaFileAnalysis:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        sanitized = _strip_comments_and_strings(lines)
        relative_path = path.relative_to(self.root).as_posix()
        methods = _extract_methods(sanitized)
        classes = _extract_classes(sanitized)
        return JavaFileAnalysis(path, relative_path, lines, sanitized, methods, classes)

    def _analyze_files(self, paths: list[Path]) -> list[JavaFileAnalysis]:
        if self._ast_analyzer is None:
            return [self._analyze_file(path) for path in paths]
        try:
            ast_by_path = {analysis.relative_path: analysis for analysis in self._ast_analyzer.analyze_files(paths)}
        except JavaAstError as err:
            self.warnings.append(f"JavaParser AST 解析不可用，已降级为文本启发式扫描: {err}")
            return [self._analyze_file(path) for path in paths]

        analyses: list[JavaFileAnalysis] = []
        for path in paths:
            relative_path = path.relative_to(self.root).as_posix()
            ast_analysis = ast_by_path.get(relative_path)
            if ast_analysis is None:
                analyses.append(self._analyze_file(path))
            else:
                analyses.append(self._analysis_from_ast(ast_analysis))
        return analyses

    def _analysis_from_ast(self, ast_analysis: AstFileAnalysis) -> JavaFileAnalysis:
        lines = ast_analysis.path.read_text(encoding="utf-8", errors="replace").splitlines()
        sanitized = _strip_comments_and_strings(lines)
        methods = [
            JavaMethod(
                name=method.name,
                start_line=method.start_line,
                end_line=method.end_line,
                body_lines=sanitized[method.start_line - 1 : method.end_line],
                signature=method.signature,
                declaring_type=method.declaring_type,
                resolved_signature=method.resolved_signature,
                symbol_resolved=method.symbol_resolved,
                is_private=method.is_private,
                is_static=method.is_static,
                method_calls=[
                    call
                    for call in ast_analysis.method_calls
                    if method.start_line <= call.start_line <= method.end_line
                ],
                field_accesses=[
                    access
                    for access in ast_analysis.field_accesses
                    if method.start_line <= access.start_line <= method.end_line
                ],
            )
            for method in ast_analysis.methods
        ]
        classes = [
            JavaClass(
                name=class_info.name,
                start_line=class_info.start_line,
                end_line=class_info.end_line,
                body_lines=sanitized[class_info.start_line - 1 : class_info.end_line],
                kind=class_info.kind,
            )
            for class_info in ast_analysis.classes
        ]
        return JavaFileAnalysis(
            path=ast_analysis.path,
            relative_path=ast_analysis.relative_path,
            lines=lines,
            sanitized_lines=sanitized,
            methods=methods,
            classes=classes,
        )

    def _scan_long_methods(self, analyses: Iterable[JavaFileAnalysis]) -> list[RefactorIssue]:
        issues: list[RefactorIssue] = []
        for analysis in analyses:
            for method in analysis.methods:
                line_count = method.end_line - method.start_line + 1
                branch_count = _count_branches(method.body_lines)
                nesting_depth = _max_control_nesting(method.body_lines)
                if line_count <= 80 and branch_count <= 12 and nesting_depth <= 4:
                    continue

                severity = (
                    Severity.HIGH
                    if line_count > 160 or branch_count > 20 or nesting_depth > 6
                    else Severity.MEDIUM
                )
                issues.append(
                    _issue(
                        SmellType.LONG_METHOD,
                        severity,
                        analysis.relative_path,
                        method.name,
                        method.start_line,
                        method.end_line,
                        [
                            Evidence(
                                "方法规模或控制流复杂度超过阈值。",
                                {"lines": line_count, "branches": branch_count, "max_nesting": nesting_depth},
                            )
                        ],
                        "长方法会让职责边界模糊，增加理解、测试和安全重构成本。",
                        "优先识别连续的业务步骤并使用 Extract Method 小步拆分。",
                        RefactoringType.EXTRACT_METHOD,
                        auto_applicable=severity != Severity.HIGH,
                        risk_level=RiskLevel.MEDIUM if severity == Severity.MEDIUM else RiskLevel.HIGH,
                        requires_review=severity == Severity.HIGH,
                    )
                )
        return issues

    def _scan_large_classes(self, analyses: Iterable[JavaFileAnalysis]) -> list[RefactorIssue]:
        issues: list[RefactorIssue] = []
        for analysis in analyses:
            for class_info in analysis.classes:
                class_methods = [
                    method
                    for method in analysis.methods
                    if class_info.start_line <= method.start_line <= class_info.end_line
                ]
                body = class_info.body_lines
                loc = class_info.end_line - class_info.start_line + 1
                field_count = _count_fields(body)
                public_method_count = sum(1 for method in class_methods if " public " in f" {method.signature} ")
                if loc <= 500 and len(class_methods) <= 20 and field_count <= 20 and public_method_count <= 15:
                    continue

                severity = (
                    Severity.HIGH
                    if loc > 1000 or len(class_methods) > 40 or field_count > 40
                    else Severity.MEDIUM
                )
                issues.append(
                    _issue(
                        SmellType.LARGE_CLASS,
                        severity,
                        analysis.relative_path,
                        class_info.name,
                        class_info.start_line,
                        class_info.end_line,
                        [
                            Evidence(
                                "类的规模或成员数量超过阈值。",
                                {
                                    "lines": loc,
                                    "methods": len(class_methods),
                                    "fields": field_count,
                                    "public_methods": public_method_count,
                                },
                            )
                        ],
                        "过大类通常承担多种职责，会放大修改影响面并降低内聚性。",
                        "优先生成 Extract Class / Move Method 计划，MVP 默认不自动执行。",
                        RefactoringType.EXTRACT_CLASS,
                        auto_applicable=False,
                        risk_level=RiskLevel.HIGH,
                        requires_review=True,
                    )
                )
        return issues

    def _scan_complex_conditions(self, analyses: Iterable[JavaFileAnalysis]) -> list[RefactorIssue]:
        issues: list[RefactorIssue] = []
        condition_pattern = re.compile(r"\b(if|while|for)\s*\((.*)\)")
        for analysis in analyses:
            for method in analysis.methods:
                nesting_depth = _max_control_nesting(method.body_lines)
                if nesting_depth > 4:
                    issues.append(
                        _issue(
                            SmellType.COMPLEX_CONDITION,
                            Severity.MEDIUM,
                            analysis.relative_path,
                            method.name,
                            method.start_line,
                            method.end_line,
                            [Evidence("控制流嵌套较深。", {"max_nesting": nesting_depth})],
                            "深层嵌套会隐藏边界条件，增加遗漏分支和回归风险。",
                            "优先使用 Guard Clauses 或 Extract Method 分解条件逻辑。",
                            RefactoringType.INTRODUCE_EXPLAINING_VARIABLE,
                            auto_applicable=False,
                            risk_level=RiskLevel.MEDIUM,
                            requires_review=True,
                        )
                    )
                    continue

                for offset, line in enumerate(method.body_lines, start=method.start_line):
                    match = condition_pattern.search(line)
                    if not match:
                        continue
                    condition = match.group(2)
                    operator_count = condition.count("&&") + condition.count("||")
                    if operator_count < 3:
                        continue
                    severity = Severity.MEDIUM if operator_count >= 4 else Severity.LOW
                    issues.append(
                        _issue(
                            SmellType.COMPLEX_CONDITION,
                            severity,
                            analysis.relative_path,
                            method.name,
                            offset,
                            offset,
                            [Evidence("布尔表达式包含较多逻辑操作符。", {"boolean_operators": operator_count})],
                            "复杂条件降低可读性，也让测试用例更难覆盖所有组合。",
                            "提取解释性变量或小方法，给关键业务判断命名。",
                            RefactoringType.INTRODUCE_EXPLAINING_VARIABLE,
                            auto_applicable=severity == Severity.LOW,
                            risk_level=RiskLevel.LOW if severity == Severity.LOW else RiskLevel.MEDIUM,
                            requires_review=severity != Severity.LOW,
                        )
                    )
        return issues

    def _scan_unclear_naming(self, analyses: Iterable[JavaFileAnalysis]) -> list[RefactorIssue]:
        issues: list[RefactorIssue] = []
        local_pattern = re.compile(
            r"\b(?:String|int|long|double|float|boolean|char|byte|short|var|[A-Z][A-Za-z0-9_<>]*)\s+"
            r"([A-Za-z_][A-Za-z0-9_]*)\s*(?:=|;|,)"
        )
        for analysis in analyses:
            for class_info in analysis.classes:
                if class_info.name.endswith(UNCLEAR_CLASS_SUFFIXES):
                    issues.append(
                        self._naming_issue(
                            analysis.relative_path,
                            class_info.name,
                            class_info.start_line,
                            f"类名 {class_info.name} 过于泛化。",
                            "类名应表达主要职责，避免 Manager/Helper/Util 泛化命名。",
                        )
                    )
            for method in analysis.methods:
                if method.name in UNCLEAR_METHOD_NAMES:
                    issues.append(
                        self._naming_issue(
                            analysis.relative_path,
                            method.name,
                            method.start_line,
                            f"方法名 {method.name} 含义泛化。",
                            "方法名应描述具体业务动作，降低调用方理解成本。",
                        )
                    )
                for offset, line in enumerate(method.body_lines, start=method.start_line):
                    for name in local_pattern.findall(line):
                        if name in UNCLEAR_LOCAL_NAMES:
                            issues.append(
                                self._naming_issue(
                                    analysis.relative_path,
                                    name,
                                    offset,
                                    f"局部变量名 {name} 含义不清晰。",
                                    "局部变量名应表达其业务含义或中间结果含义。",
                                )
                            )
        return issues

    def _naming_issue(
        self,
        file_path: str,
        symbol: str,
        line: int,
        evidence_message: str,
        recommendation: str,
    ) -> RefactorIssue:
        return _issue(
            SmellType.UNCLEAR_NAMING,
            Severity.LOW,
            file_path,
            symbol,
            line,
            line,
            [Evidence(evidence_message)],
            "命名不清晰会让代码意图依赖上下文猜测，增加维护和 Review 成本。",
            recommendation,
            RefactoringType.RENAME,
            auto_applicable=True,
            risk_level=RiskLevel.LOW,
            requires_review=False,
        )

    def _scan_dead_code(self, analyses: list[JavaFileAnalysis]) -> list[RefactorIssue]:
        source_text = "\n".join("\n".join(analysis.sanitized_lines) for analysis in analyses)
        name_counts = Counter(re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", source_text))
        resolved_calls = {
            call.resolved_signature
            for analysis in analyses
            for method in analysis.methods
            for call in method.method_calls
            if call.symbol_resolved and call.resolved_signature
        }
        issues: list[RefactorIssue] = []
        for analysis in analyses:
            for method in analysis.methods:
                if not method.is_private or method.name in {"main"}:
                    continue
                has_symbol_data = bool(method.symbol_resolved and method.resolved_signature)
                if has_symbol_data and method.resolved_signature in resolved_calls:
                    continue
                if not has_symbol_data and name_counts[method.name] > 1:
                    continue
                source = "symbol-solver" if has_symbol_data else "identifier-count-fallback"
                issues.append(
                    _issue(
                        SmellType.DEAD_CODE,
                        Severity.LOW,
                        analysis.relative_path,
                        method.name,
                        method.start_line,
                        method.end_line,
                        [
                            Evidence(
                                "private 方法未发现其它引用。",
                                {
                                    "identifier_occurrences": name_counts[method.name],
                                    "source": source,
                                    "resolved_signature": method.resolved_signature,
                                },
                            )
                        ],
                        "无用 private 代码会增加阅读负担，也可能误导后续重构判断。",
                        "确认无反射或框架调用后使用 Remove Dead Code。",
                        RefactoringType.REMOVE_DEAD_CODE,
                        auto_applicable=True,
                        risk_level=RiskLevel.LOW,
                        requires_review=False,
                    )
                )
        return issues

    def _scan_feature_envy(self, analyses: Iterable[JavaFileAnalysis]) -> list[RefactorIssue]:
        issues: list[RefactorIssue] = []
        for analysis in analyses:
            for method in analysis.methods:
                if method.is_private or not method.symbol_resolved or not method.declaring_type:
                    continue
                external_calls = [
                    call
                    for call in method.method_calls
                    if call.symbol_resolved
                    and call.declaring_type
                    and not _same_or_nested_type(call.declaring_type, method.declaring_type)
                    and not call.declaring_type.startswith("java.")
                ]
                external_fields = [
                    access
                    for access in method.field_accesses
                    if access.symbol_resolved
                    and access.declaring_type
                    and not _same_or_nested_type(access.declaring_type, method.declaring_type)
                    and not access.declaring_type.startswith("java.")
                ]
                local_calls = [
                    call
                    for call in method.method_calls
                    if call.symbol_resolved and _same_or_nested_type(call.declaring_type, method.declaring_type)
                ]
                local_fields = [
                    access
                    for access in method.field_accesses
                    if access.symbol_resolved and _same_or_nested_type(access.declaring_type, method.declaring_type)
                ]
                external_total = len(external_calls) + len(external_fields)
                local_total = len(local_calls) + len(local_fields)
                if external_total < 5 or external_total < max(local_total * 2, 3):
                    continue

                external_types = Counter(
                    item.declaring_type for item in [*external_calls, *external_fields] if item.declaring_type
                )
                dominant_type, dominant_count = external_types.most_common(1)[0]
                if dominant_count < 4:
                    continue

                issues.append(
                    _issue(
                        SmellType.FEATURE_ENVY,
                        Severity.MEDIUM,
                        analysis.relative_path,
                        method.name,
                        method.start_line,
                        method.end_line,
                        [
                            Evidence(
                                "方法访问外部类型成员明显多于本类成员。",
                                {
                                    "source": "javaparser-symbol-solver",
                                    "declaring_type": method.declaring_type,
                                    "dominant_external_type": dominant_type,
                                    "external_member_uses": external_total,
                                    "local_member_uses": local_total,
                                    "external_method_calls": len(external_calls),
                                    "external_field_accesses": len(external_fields),
                                },
                            )
                        ],
                        "Feature Envy 通常说明方法逻辑更依赖其它类型的数据或行为，可能导致职责放错位置。",
                        "优先评估 Move Method、Extract Method 或把外部数据访问封装到目标类型内。",
                        RefactoringType.MOVE_METHOD,
                        auto_applicable=False,
                        risk_level=RiskLevel.MEDIUM,
                        requires_review=True,
                    )
                )
        return issues

    def _scan_duplicate_code(self, analyses: list[JavaFileAnalysis]) -> list[RefactorIssue]:
        issues = self._scan_duplicate_code_with_cpd()
        if issues:
            return issues

        windows: dict[tuple[str, ...], list[tuple[JavaFileAnalysis, int]]] = defaultdict(list)
        window_size = 6
        for analysis in analyses:
            normalized_lines = [_normalize_duplicate_line(line) for line in analysis.sanitized_lines]
            indexed = [(index, line) for index, line in enumerate(normalized_lines, start=1) if line]
            for index in range(0, max(0, len(indexed) - window_size + 1)):
                start_line = indexed[index][0]
                block = tuple(line for _, line in indexed[index : index + window_size])
                if len(set(block)) <= 1:
                    continue
                windows[block].append((analysis, start_line))

        duplicate_issues: list[RefactorIssue] = []
        seen_blocks: set[tuple[str, ...]] = set()
        for block, locations in windows.items():
            unique_locations = {(item.relative_path, line) for item, line in locations}
            if len(unique_locations) < 2 or block in seen_blocks:
                continue
            seen_blocks.add(block)
            first_analysis, first_line = locations[0]
            duplicate_issues.append(
                _issue(
                    SmellType.DUPLICATE_CODE,
                    Severity.MEDIUM,
                    first_analysis.relative_path,
                    None,
                    first_line,
                    first_line + window_size - 1,
                    [
                        Evidence(
                            "发现重复代码片段。",
                            {
                                "duplicate_locations": [
                                    {"file": analysis.relative_path, "start_line": line}
                                    for analysis, line in locations[:5]
                                ],
                                "source": "local-fallback",
                            },
                        )
                    ],
                    "重复代码会让缺陷修复和规则调整需要多处同步，容易出现行为漂移。",
                    "优先考虑 Extract Method 或提取共享逻辑。",
                    RefactoringType.REPLACE_DUPLICATE_LOGIC,
                    auto_applicable=False,
                    risk_level=RiskLevel.MEDIUM,
                    requires_review=True,
                )
            )
            if len(duplicate_issues) >= 20:
                break
        return duplicate_issues

    def _scan_duplicate_code_with_cpd(self) -> list[RefactorIssue]:
        try:
            result = self._run(["mvn", "-q", "pmd:cpd-check"], self.root)
        except (FileNotFoundError, subprocess.SubprocessError, OSError):
            self.warnings.append("无法执行 PMD CPD，已使用本地重复代码兜底规则。")
            return []

        output = "\n".join(part for part in [result.stdout, result.stderr] if part)
        if result.returncode == 0:
            return []
        parsed = _parse_cpd_output(output, self.root)
        if not parsed:
            self.warnings.append("PMD CPD 未返回可解析重复代码，已使用本地重复代码兜底规则。")
        return parsed


def _issue(
    smell_type: SmellType,
    severity: Severity,
    file_path: str,
    symbol: str | None,
    start_line: int,
    end_line: int,
    evidence: list[Evidence],
    impact: str,
    recommendation: str,
    suggested_refactoring: RefactoringType,
    *,
    auto_applicable: bool,
    risk_level: RiskLevel,
    requires_review: bool,
) -> RefactorIssue:
    return RefactorIssue(
        id="",
        type=smell_type,
        severity=severity,
        file_path=file_path,
        symbol=symbol,
        start_line=start_line,
        end_line=end_line,
        evidence=evidence,
        impact=impact,
        recommendation=recommendation,
        suggested_refactoring=suggested_refactoring,
        auto_applicable=auto_applicable,
        risk_level=risk_level,
        requires_review=requires_review,
    )


def _strip_comments_and_strings(lines: list[str]) -> list[str]:
    sanitized: list[str] = []
    in_block_comment = False
    for line in lines:
        index = 0
        output = []
        in_string: str | None = None
        while index < len(line):
            current = line[index]
            next_char = line[index + 1] if index + 1 < len(line) else ""
            if in_block_comment:
                if current == "*" and next_char == "/":
                    in_block_comment = False
                    index += 2
                else:
                    index += 1
                continue
            if in_string:
                if current == "\\":
                    index += 2
                    continue
                if current == in_string:
                    in_string = None
                output.append(" ")
                index += 1
                continue
            if current == "/" and next_char == "/":
                break
            if current == "/" and next_char == "*":
                in_block_comment = True
                index += 2
                continue
            if current in {'"', "'"}:
                in_string = current
                output.append(" ")
                index += 1
                continue
            output.append(current)
            index += 1
        sanitized.append("".join(output))
    return sanitized


def _extract_methods(lines: list[str]) -> list[JavaMethod]:
    methods: list[JavaMethod] = []
    pending_signature: list[tuple[int, str]] = []
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if not line:
            pending_signature.clear()
            index += 1
            continue
        if pending_signature or _looks_like_method_signature_start(line):
            pending_signature.append((index + 1, line))
            signature = " ".join(part for _, part in pending_signature)
            if "{" not in line:
                index += 1
                continue
            if _is_method_signature(signature):
                start_line = pending_signature[0][0]
                end_index = _find_block_end(lines, index)
                name = _method_name(signature)
                if name:
                    body_lines = lines[index : end_index + 1]
                    methods.append(
                        JavaMethod(
                            name=name,
                            start_line=start_line,
                            end_line=end_index + 1,
                            body_lines=body_lines,
                            signature=signature,
                            declaring_type="",
                            resolved_signature="",
                            symbol_resolved=False,
                            is_private=bool(re.search(r"\bprivate\b", signature)),
                            is_static=bool(re.search(r"\bstatic\b", signature)),
                            method_calls=[],
                            field_accesses=[],
                        )
                    )
                    pending_signature.clear()
                    index = end_index + 1
                    continue
            pending_signature.clear()
        index += 1
    return methods


def _looks_like_method_signature_start(line: str) -> bool:
    if line.startswith(("@", "if ", "for ", "while ", "switch ", "catch ", "return ", "new ")):
        return False
    return "(" in line and not line.endswith(";")


def _is_method_signature(signature: str) -> bool:
    prefix = signature.split("(", 1)[0]
    if "=" in prefix or "->" in signature:
        return False
    if re.search(r"\b(if|for|while|switch|catch|synchronized|try|new)\s*\(", signature):
        return False
    if re.search(r"\b(class|interface|enum|record)\b", prefix):
        return False
    return _method_name(signature) is not None


def _method_name(signature: str) -> str | None:
    match = re.search(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\([^;{}]*\)\s*(?:throws\s+[A-Za-z0-9_.,\s]+)?\{", signature)
    if not match:
        return None
    return match.group(1)


def _extract_classes(lines: list[str]) -> list[JavaClass]:
    classes: list[JavaClass] = []
    pattern = re.compile(r"\b(class|interface|enum|record)\s+([A-Za-z_][A-Za-z0-9_]*)")
    for index, line in enumerate(lines):
        match = pattern.search(line)
        if not match:
            continue
        end_index = _find_block_end(lines, index)
        classes.append(
            JavaClass(
                name=match.group(2),
                start_line=index + 1,
                end_line=end_index + 1,
                body_lines=lines[index : end_index + 1],
                kind=match.group(1),
            )
        )
    return classes


def _find_block_end(lines: list[str], start_index: int) -> int:
    depth = 0
    seen_open = False
    for index in range(start_index, len(lines)):
        line = lines[index]
        depth += line.count("{")
        if line.count("{"):
            seen_open = True
        depth -= line.count("}")
        if seen_open and depth <= 0:
            return index
    return len(lines) - 1


def _count_branches(lines: list[str]) -> int:
    return sum(len(re.findall(r"\b(if|else\s+if|switch|case|for|while|catch)\b", line)) for line in lines)


def _max_control_nesting(lines: list[str]) -> int:
    depth = 0
    max_depth = 0
    control_stack: list[int] = []
    control_pattern = re.compile(r"\b(if|else\s+if|else|for|while|switch|try|catch)\b")
    for line in lines:
        stripped = line.strip()
        closing = stripped.count("}")
        if closing:
            depth = max(0, depth - closing)
            control_stack = [item for item in control_stack if item <= depth]
        if control_pattern.search(stripped):
            max_depth = max(max_depth, depth + 1)
            control_stack.append(depth + 1)
        opening = stripped.count("{")
        if opening:
            depth += opening
    return max_depth


def _count_fields(lines: list[str]) -> int:
    count = 0
    field_pattern = re.compile(
        r"^\s*(?:private|protected|public)?\s*(?:static\s+)?(?:final\s+)?[A-Za-z_][A-Za-z0-9_<>\[\], ?]*\s+"
        r"[A-Za-z_][A-Za-z0-9_]*\s*(?:=|;)"
    )
    for line in lines:
        stripped = line.strip()
        if "(" in stripped or stripped.startswith(("@", "//")):
            continue
        if field_pattern.search(line):
            count += 1
    return count


def _normalize_duplicate_line(line: str) -> str:
    stripped = line.strip()
    if not stripped or stripped in {"{", "}"}:
        return ""
    stripped = re.sub(r"\b\d+\b", "0", stripped)
    stripped = re.sub(r"\s+", " ", stripped)
    return stripped


def _same_or_nested_type(candidate: str, owner: str) -> bool:
    return bool(candidate and owner and (candidate == owner or candidate.startswith(owner + ".")))


def _parse_cpd_output(output: str, root: Path) -> list[RefactorIssue]:
    issues: list[RefactorIssue] = []
    current_lines = 0
    current_locations: list[tuple[str, int]] = []
    duplication_pattern = re.compile(r"Found a\s+(\d+)\s+line.*duplication", re.IGNORECASE)
    location_pattern = re.compile(r"Starting at line\s+(\d+)\s+of\s+(.+)", re.IGNORECASE)

    for raw_line in output.splitlines():
        line = raw_line.strip()
        duplication_match = duplication_pattern.search(line)
        if duplication_match:
            if current_locations:
                issues.append(_cpd_issue(current_lines, current_locations))
            current_lines = int(duplication_match.group(1))
            current_locations = []
            continue

        location_match = location_pattern.search(line)
        if location_match:
            file_path = Path(location_match.group(2).strip())
            try:
                relative = file_path.resolve().relative_to(root).as_posix()
            except (OSError, ValueError):
                relative = file_path.as_posix()
            current_locations.append((relative, int(location_match.group(1))))

    if current_locations:
        issues.append(_cpd_issue(current_lines, current_locations))
    return issues


def _cpd_issue(line_count: int, locations: list[tuple[str, int]]) -> RefactorIssue:
    first_file, first_line = locations[0]
    return _issue(
        SmellType.DUPLICATE_CODE,
        Severity.MEDIUM if line_count < 40 else Severity.HIGH,
        first_file,
        None,
        first_line,
        first_line + max(line_count - 1, 0),
        [
            Evidence(
                "PMD CPD 发现重复代码。",
                {
                    "lines": line_count,
                    "duplicate_locations": [{"file": file_path, "start_line": line} for file_path, line in locations],
                    "source": "pmd-cpd",
                },
            )
        ],
        "重复代码会让缺陷修复和规则调整需要多处同步，容易出现行为漂移。",
        "优先考虑 Extract Method 或提取共享逻辑。",
        RefactoringType.REPLACE_DUPLICATE_LOGIC,
        auto_applicable=False,
        risk_level=RiskLevel.MEDIUM,
        requires_review=True,
    )
