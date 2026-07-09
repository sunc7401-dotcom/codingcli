"""JavaParser-backed AST extraction for Java source files."""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

CommandRunner = Callable[[Sequence[str], Path], subprocess.CompletedProcess[str]]


class JavaAstError(Exception):
    """Raised when JavaParser AST extraction is unavailable or invalid."""


@dataclass(frozen=True)
class AstMethod:
    name: str
    start_line: int
    end_line: int
    signature: str
    is_private: bool
    is_static: bool


@dataclass(frozen=True)
class AstClass:
    name: str
    start_line: int
    end_line: int
    kind: str


@dataclass(frozen=True)
class AstFileAnalysis:
    path: Path
    relative_path: str
    methods: list[AstMethod]
    classes: list[AstClass]


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
        timeout=180,
    )


class JavaParserAnalyzer:
    """Run the bundled JavaParser helper and return source ranges from a real Java AST."""

    def __init__(self, root: str | Path, command_runner: CommandRunner | None = None) -> None:
        self.root = Path(root).resolve()
        self._run = command_runner or _default_command_runner
        self.helper_dir = Path(__file__).resolve().parent / "java_ast_helper"

    def analyze_files(self, paths: list[Path]) -> list[AstFileAnalysis]:
        if not paths:
            return []
        relative_paths = [self._relative_path(path) for path in paths]
        args = " ".join([_quote_arg(str(self.root)), *[_quote_arg(path) for path in relative_paths]])
        command = [
            "mvn",
            "-q",
            "-f",
            str(self.helper_dir / "pom.xml"),
            "compile",
            "exec:java",
            f"-Dexec.args={args}",
        ]
        try:
            result = self._run(command, self.root)
        except (FileNotFoundError, OSError, subprocess.SubprocessError) as err:
            raise JavaAstError(f"JavaParser helper failed to start: {err}") from err
        if result.returncode != 0:
            output = (result.stderr or result.stdout or "").strip()
            raise JavaAstError(f"JavaParser helper failed: {output[-1000:]}")
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError as err:
            raise JavaAstError("JavaParser helper returned invalid JSON.") from err
        return [_ast_file_from_dict(item, self.root) for item in data.get("files", [])]

    def _relative_path(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.root).as_posix()
        except ValueError as err:
            raise JavaAstError(f"Java source path is outside project root: {path}") from err


def _ast_file_from_dict(data: dict, root: Path) -> AstFileAnalysis:
    relative_path = str(data["path"]).replace("\\", "/")
    return AstFileAnalysis(
        path=(root / relative_path).resolve(),
        relative_path=relative_path,
        methods=[
            AstMethod(
                name=item["name"],
                start_line=int(item["start_line"]),
                end_line=int(item["end_line"]),
                signature=item.get("signature", ""),
                is_private=bool(item.get("is_private", False)),
                is_static=bool(item.get("is_static", False)),
            )
            for item in data.get("methods", [])
        ],
        classes=[
            AstClass(
                name=item["name"],
                start_line=int(item["start_line"]),
                end_line=int(item["end_line"]),
                kind=item.get("kind", "class"),
            )
            for item in data.get("classes", [])
        ],
    )


def _quote_arg(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
