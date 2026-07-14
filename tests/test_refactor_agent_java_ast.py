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
    assert [analysis.relative_path for analysis in scanner.ast_analyses] == [
        "src/main/java/demo/OrderService.java"
    ]
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


def test_javaparser_supports_records(tmp_path: Path) -> None:
    source_dir = tmp_path / "src" / "main" / "java" / "demo"
    source_dir.mkdir(parents=True)
    record_path = source_dir / "OrderLine.java"
    record_path.write_text(
        """
package demo;

public record OrderLine(String sku, int quantity, int unitPrice) {
    public int subtotal() {
        return quantity * unitPrice;
    }
}
""".lstrip(),
        encoding="utf-8",
    )

    analysis = JavaParserAnalyzer(tmp_path).analyze_files([record_path])[0]

    record_class = next(item for item in analysis.classes if item.name == "OrderLine")
    subtotal = next(method for method in analysis.methods if method.name == "subtotal")
    assert record_class.kind == "record"
    assert record_class.field_count == 3
    assert record_class.method_count == 1
    assert record_class.public_method_count == 1
    assert subtotal.declaring_type == "demo.OrderLine"


def test_javaparser_counts_direct_class_members_from_ast(tmp_path: Path) -> None:
    source_dir = tmp_path / "src" / "main" / "java" / "demo"
    source_dir.mkdir(parents=True)
    source_path = source_dir / "MemberCounts.java"
    source_path.write_text(
        """
package demo;

public class MemberCounts {
    private int first, second;
    private final String value = String.valueOf(1);

    public MemberCounts() {}
    public void visible() {}
    private void hidden() {}

    static class Nested {
        int nestedField;
        public void nestedMethod() {}
    }
}
""".lstrip(),
        encoding="utf-8",
    )

    analysis = JavaParserAnalyzer(tmp_path).analyze_files([source_path])[0]

    outer = next(item for item in analysis.classes if item.name == "MemberCounts")
    nested = next(item for item in analysis.classes if item.name == "Nested")
    assert (outer.field_count, outer.method_count, outer.public_method_count) == (3, 3, 2)
    assert (nested.field_count, nested.method_count, nested.public_method_count) == (1, 1, 1)


def test_scanner_uses_ast_class_metrics_instead_of_source_regex(tmp_path: Path) -> None:
    source_dir = tmp_path / "src" / "main" / "java" / "demo"
    source_dir.mkdir(parents=True)
    source_path = source_dir / "ManyFields.java"
    declarations = "\n".join(
        f"    private final String field{index} = String.valueOf({index});" for index in range(21)
    )
    source_path.write_text(
        f"package demo;\npublic class ManyFields {{\n{declarations}\n}}\n",
        encoding="utf-8",
    )

    issues = JavaSmellScanner(tmp_path, command_runner=_pmd_runner).scan()

    large_class = next(issue for issue in issues if issue.type == SmellType.LARGE_CLASS)
    assert large_class.evidence[0].metrics["fields"] == 21


def test_javaparser_calculates_control_flow_metrics_from_ast(tmp_path: Path) -> None:
    source_dir = tmp_path / "src" / "main" / "java" / "demo"
    source_dir.mkdir(parents=True)
    source_path = source_dir / "ControlFlow.java"
    source_path.write_text(
        """
package demo;

public class ControlFlow {
    public void inspect(int value) {
        if (value > 0) { // } misleading brace in a comment
            for (int index = 0; index < value; index++) {
                while (value-- > index) {
                    System.out.println("if (fake) { }");
                }
            }
        }
    }
}
""".lstrip(),
        encoding="utf-8",
    )

    analysis = JavaParserAnalyzer(tmp_path).analyze_files([source_path])[0]

    method = next(item for item in analysis.methods if item.name == "inspect")
    assert method.branch_count == 3
    assert method.max_control_nesting == 3


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
