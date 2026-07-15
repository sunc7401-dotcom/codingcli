"""JaCoCo coverage awareness for refactor-agent verification."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from suncli_py.refactor_agent.core.models import CoverageAssessment, RefactorIssue, RefactorPlan


@dataclass(frozen=True)
class _SourceCoverage:
    report_found: bool = False
    source_found: bool = False
    issue_lines_covered: int = 0
    file_lines_total: int = 0
    file_lines_covered: int = 0


class CoverageAnalyzer:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

    def assess(self, plan: RefactorPlan, issue: RefactorIssue) -> CoverageAssessment:
        total_lines = max(issue.end_line - issue.start_line + 1, 0)
        measured = self._measure_source(issue)
        if not measured.report_found:
            return CoverageAssessment(
                has_related_test_class=plan.coverage_assessment.has_related_test_class,
                related_tests=plan.coverage_assessment.related_tests,
                confidence="medium" if plan.coverage_assessment.has_related_test_class else "low",
                needs_characterization_test=True,
                recommendation="未找到 JaCoCo XML 覆盖报告，不能证明目标代码已被测试覆盖。",
                jacoco_report_found=False,
                changed_lines_total=total_lines,
                changed_lines_covered=0,
                coverage_ratio=0.0,
                generated_tests=plan.coverage_assessment.generated_tests,
            )

        ratio = measured.issue_lines_covered / total_lines if total_lines else 0.0
        enough = measured.source_found and total_lines > 0 and ratio >= 0.8
        confidence = "high" if enough else ("medium" if plan.coverage_assessment.has_related_test_class else "low")
        if not measured.source_found:
            recommendation = "JaCoCo 报告中没有目标源文件记录，需要先补充能执行该文件行为的测试。"
        elif enough:
            recommendation = "JaCoCo 显示目标修改区域已有充分覆盖。"
        else:
            recommendation = "JaCoCo 显示目标区域覆盖不足，需要在修改前补充行为锁定测试。"
        return CoverageAssessment(
            has_related_test_class=plan.coverage_assessment.has_related_test_class,
            related_tests=plan.coverage_assessment.related_tests,
            confidence=confidence,
            needs_characterization_test=not enough,
            recommendation=recommendation,
            jacoco_report_found=True,
            changed_lines_total=total_lines,
            changed_lines_covered=measured.issue_lines_covered,
            coverage_ratio=round(ratio, 4),
            generated_tests=plan.coverage_assessment.generated_tests,
            target_file_lines_total=measured.file_lines_total,
            target_file_lines_covered=measured.file_lines_covered,
        )

    def _measure_source(self, issue: RefactorIssue) -> _SourceCoverage:
        reports = sorted(
            self.root.glob("**/target/site/jacoco/jacoco.xml"),
            key=lambda report: self._report_rank(report, issue.file_path),
        )
        if not reports:
            return _SourceCoverage()

        expected_suffix = issue.file_path.replace("\\", "/")
        valid_report_found = False
        for report in reports:
            try:
                root = ET.parse(report).getroot()
            except (ET.ParseError, OSError):
                continue
            valid_report_found = True
            for package in root.findall("package"):
                package_name = package.attrib.get("name", "")
                for sourcefile in package.findall("sourcefile"):
                    source_path = f"{package_name}/{sourcefile.attrib.get('name', '')}".lstrip("/")
                    if not expected_suffix.endswith(source_path):
                        continue
                    issue_covered = 0
                    file_total = 0
                    file_covered = 0
                    for line in sourcefile.findall("line"):
                        try:
                            line_number = int(line.attrib.get("nr", "0"))
                            covered = int(line.attrib.get("ci", "0")) > 0
                        except ValueError:
                            continue
                        file_total += 1
                        file_covered += int(covered)
                        if issue.start_line <= line_number <= issue.end_line and covered:
                            issue_covered += 1
                    return _SourceCoverage(True, True, issue_covered, file_total, file_covered)
        return _SourceCoverage(report_found=valid_report_found)

    def _report_rank(self, report: Path, source_file: str) -> tuple[int, str]:
        source_parts = Path(source_file.replace("\\", "/")).parts
        module_parts: tuple[str, ...] = ()
        for index in range(max(0, len(source_parts) - 2)):
            if source_parts[index : index + 3] == ("src", "main", "java"):
                module_parts = source_parts[:index]
                break
        report_parts = report.relative_to(self.root).parts
        in_target_module = not module_parts or report_parts[: len(module_parts)] == module_parts
        return (0 if in_target_module else 1, report.as_posix())
