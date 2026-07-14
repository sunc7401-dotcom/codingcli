"""JaCoCo coverage awareness for refactor-agent verification."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from suncli_py.refactor_agent.core.models import CoverageAssessment, RefactorIssue, RefactorPlan


class CoverageAnalyzer:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

    def assess(self, plan: RefactorPlan, issue: RefactorIssue) -> CoverageAssessment:
        report = self._find_jacoco_report()
        total_lines = max(issue.end_line - issue.start_line + 1, 0)
        if report is None:
            return CoverageAssessment(
                has_related_test_class=plan.coverage_assessment.has_related_test_class,
                related_tests=plan.coverage_assessment.related_tests,
                confidence="medium" if plan.coverage_assessment.has_related_test_class else "low",
                needs_characterization_test=True,
                recommendation="未找到 JaCoCo XML 覆盖报告，不能证明本次修改区域已被测试覆盖。",
                jacoco_report_found=False,
                changed_lines_total=total_lines,
                changed_lines_covered=0,
                coverage_ratio=0.0,
                generated_tests=plan.coverage_assessment.generated_tests,
            )

        covered = self._covered_lines(report, issue)
        ratio = covered / total_lines if total_lines else 0.0
        enough = total_lines > 0 and ratio >= 0.8
        confidence = "high" if enough else ("medium" if plan.coverage_assessment.has_related_test_class else "low")
        recommendation = (
            "JaCoCo 显示目标修改行覆盖充分。"
            if enough
            else "JaCoCo 覆盖不足，验证结果只能作为警告级证据，建议补充 characterization test。"
        )
        return CoverageAssessment(
            has_related_test_class=plan.coverage_assessment.has_related_test_class,
            related_tests=plan.coverage_assessment.related_tests,
            confidence=confidence,
            needs_characterization_test=not enough,
            recommendation=recommendation,
            jacoco_report_found=True,
            changed_lines_total=total_lines,
            changed_lines_covered=covered,
            coverage_ratio=round(ratio, 4),
            generated_tests=plan.coverage_assessment.generated_tests,
        )

    def _find_jacoco_report(self) -> Path | None:
        candidates = sorted(self.root.glob("**/target/site/jacoco/jacoco.xml"))
        return candidates[0] if candidates else None

    def _covered_lines(self, report: Path, issue: RefactorIssue) -> int:
        tree = ET.parse(report)
        root = tree.getroot()
        expected_suffix = issue.file_path.replace("\\", "/")
        covered = 0
        for package in root.findall("package"):
            package_name = package.attrib.get("name", "")
            for sourcefile in package.findall("sourcefile"):
                source_path = f"{package_name}/{sourcefile.attrib.get('name', '')}".lstrip("/")
                if not expected_suffix.endswith(source_path):
                    continue
                for line in sourcefile.findall("line"):
                    line_number = int(line.attrib.get("nr", "0"))
                    if issue.start_line <= line_number <= issue.end_line and int(line.attrib.get("ci", "0")) > 0:
                        covered += 1
                return covered
        return 0
