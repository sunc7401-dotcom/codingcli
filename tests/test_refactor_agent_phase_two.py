from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path

from suncli_py.refactor_agent.analysis.scanner import JavaSmellScanner
from suncli_py.refactor_agent.core.models import SmellType


def _runner(command: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    del cwd
    if list(command) == ["mvn", "-q", "pmd:cpd-check"]:
        output = """Found a 6 line (30 tokens) duplication in the following files:
Starting at line 130 of src/main/java/demo/OrderHelper.java
Starting at line 142 of src/main/java/demo/OrderHelper.java
"""
        return subprocess.CompletedProcess(command, 1, stdout=output, stderr="")
    return subprocess.CompletedProcess(command, 0, stdout="", stderr="")


def test_java_smell_scanner_finds_phase_two_issue_types(tmp_path: Path) -> None:
    source_dir = tmp_path / "src" / "main" / "java" / "demo"
    source_dir.mkdir(parents=True)
    (tmp_path / "pom.xml").write_text("<project />", encoding="utf-8")
    (source_dir / "OrderHelper.java").write_text(_java_source(), encoding="utf-8")

    scanner = JavaSmellScanner(tmp_path, command_runner=_runner)
    issues = scanner.scan()
    issue_types = {issue.type for issue in issues}

    assert SmellType.LONG_METHOD in issue_types
    assert SmellType.LARGE_CLASS in issue_types
    assert SmellType.COMPLEX_CONDITION in issue_types
    assert SmellType.UNCLEAR_NAMING in issue_types
    assert SmellType.DEAD_CODE in issue_types
    assert SmellType.DUPLICATE_CODE in issue_types
    assert all(issue.id.startswith("RA-") for issue in issues)
    assert all(issue.file_path.endswith(".java") for issue in issues)
    assert all(issue.start_line > 0 and issue.end_line >= issue.start_line for issue in issues)
    assert all(issue.impact and issue.recommendation for issue in issues)


def _java_source() -> str:
    fields = "\n".join(f"    private String field{i};" for i in range(25))
    long_method_lines = "\n".join(f"        total += {i};" for i in range(83))
    duplicate_block = """
        int base = input + 1;
        int tax = base * 2;
        int fee = tax + 3;
        int discount = fee - 4;
        int score = discount + input;
        return score;
    """
    return f"""
package demo;

public class OrderHelper {{
{fields}

    public int handle(int input, boolean a, boolean b, boolean c, boolean d, boolean e) {{
        int tmp = input;
        if (a && b && c && d && e) {{
            tmp++;
        }}
        return tmp;
    }}

    private void unusedPrivate() {{
        System.out.println("unused");
    }}

    public int veryLongMethod(int input) {{
        int total = input;
{long_method_lines}
        return total;
    }}

    public int duplicateOne(int input) {{
{duplicate_block}
    }}

    public int duplicateTwo(int input) {{
{duplicate_block}
    }}
}}
"""
