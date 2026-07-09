from __future__ import annotations

import json
import subprocess
from collections.abc import Sequence
from pathlib import Path

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
