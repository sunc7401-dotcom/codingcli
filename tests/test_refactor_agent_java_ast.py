from __future__ import annotations

import json
import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

from suncli_py.refactor_agent.java_ast import JavaAstError, JavaParserAnalyzer
from suncli_py.refactor_agent.models import SmellType
from suncli_py.refactor_agent.scanner import JavaSmellScanner


def test_scanner_uses_javaparser_ast_method_ranges(tmp_path: Path) -> None:
    source_dir = tmp_path / "src" / "main" / "java" / "demo"
    source_dir.mkdir(parents=True)
    source_path = source_dir / "OrderService.java"
    source_path.write_text(_java_source(), encoding="utf-8")

    scanner = JavaSmellScanner(
        tmp_path,
        command_runner=_pmd_runner,
        ast_command_runner=_ast_runner,
    )

    issues = scanner.scan()
    long_method = next(issue for issue in issues if issue.type == SmellType.LONG_METHOD)

    assert long_method.symbol == "hugeFromAst"
    assert long_method.start_line == 4
    assert long_method.end_line == 90
    assert not any("JavaParser AST 解析不可用" in warning for warning in scanner.warnings)


def test_scanner_requires_javaparser_ast(tmp_path: Path) -> None:
    source_dir = tmp_path / "src" / "main" / "java" / "demo"
    source_dir.mkdir(parents=True)
    (source_dir / "OrderService.java").write_text(_java_source(), encoding="utf-8")

    scanner = JavaSmellScanner(
        tmp_path,
        command_runner=_pmd_runner,
        ast_command_runner=_failing_ast_runner,
    )

    with pytest.raises(JavaAstError, match="JavaParser helper failed"):
        scanner.scan()
    assert scanner.warnings == []


def test_javaparser_symbol_solver_extracts_method_calls(tmp_path: Path) -> None:
    source_dir = tmp_path / "src" / "main" / "java" / "demo"
    source_dir.mkdir(parents=True)
    customer_path = source_dir / "Customer.java"
    service_path = source_dir / "OrderService.java"
    customer_path.write_text(
        """
package demo;

public class Customer {
    public int score() {
        return 1;
    }
}
""".lstrip(),
        encoding="utf-8",
    )
    service_path.write_text(
        """
package demo;

public class OrderService {
    public int create(Customer customer) {
        return customer.score();
    }
}
""".lstrip(),
        encoding="utf-8",
    )

    analysis = JavaParserAnalyzer(tmp_path).analyze_files([service_path])[0]

    score_call = next(call for call in analysis.method_calls if call.name == "score")
    assert score_call.symbol_resolved is True
    assert score_call.declaring_type == "demo.Customer"
    assert "demo.Customer.score()" in score_call.resolved_signature


def test_scanner_detects_feature_envy_with_symbol_solver(tmp_path: Path) -> None:
    source_dir = tmp_path / "src" / "main" / "java" / "demo"
    source_dir.mkdir(parents=True)
    (tmp_path / "pom.xml").write_text("<project />", encoding="utf-8")
    (source_dir / "Customer.java").write_text(
        """
package demo;

public class Customer {
    public int score() { return 1; }
    public int rank() { return 2; }
    public int level() { return 3; }
    public int age() { return 4; }
    public int weight() { return 5; }
}
""".lstrip(),
        encoding="utf-8",
    )
    (source_dir / "OrderService.java").write_text(
        """
package demo;

public class OrderService {
    public int calculate(Customer customer) {
        int total = 0;
        total += customer.score();
        total += customer.rank();
        total += customer.level();
        total += customer.age();
        total += customer.weight();
        return total;
    }
}
""".lstrip(),
        encoding="utf-8",
    )

    scanner = JavaSmellScanner(tmp_path, command_runner=_pmd_runner)
    issues = scanner.scan()
    feature_envy = next(issue for issue in issues if issue.type == SmellType.FEATURE_ENVY)

    assert feature_envy.symbol == "calculate"
    assert feature_envy.evidence[0].metrics["dominant_external_type"] == "demo.Customer"
    assert feature_envy.evidence[0].metrics["source"] == "javaparser-symbol-solver"


def _pmd_runner(command: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    del cwd
    if list(command) == ["mvn", "-q", "pmd:cpd-check"]:
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
    return subprocess.CompletedProcess(command, 0, stdout="", stderr="")


def _ast_runner(command: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    del cwd
    assert "exec:java" in command
    payload = {
        "files": [
            {
                "path": "src/main/java/demo/OrderService.java",
                "classes": [{"name": "OrderService", "start_line": 3, "end_line": 91, "kind": "class"}],
                "methods": [
                    {
                        "name": "hugeFromAst",
                        "start_line": 4,
                        "end_line": 90,
                        "signature": "public int hugeFromAst(int input)",
                        "is_private": False,
                        "is_static": False,
                    }
                ],
            }
        ]
    }
    return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload), stderr="")


def _failing_ast_runner(command: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    del cwd
    assert "exec:java" in command
    return subprocess.CompletedProcess(command, 1, stdout="", stderr="javaparser unavailable")


def _java_source() -> str:
    body = "\n".join(f"        total += {index};" for index in range(84))
    return f"""
package demo;
public class OrderService {{
    public int hugeFromAst(int input) {{
        int total = input;
{body}
        return total;
    }}
}}
""".lstrip()
