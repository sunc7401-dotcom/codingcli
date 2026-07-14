"""Load and initialize versioned PAI.md project memory."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from loguru import logger


class ProjectMemoryLoader:
    MAX_TOTAL_CHARS = 24_000
    MAX_IMPORT_DEPTH = 3

    def __init__(self, project_root: Path, user_config_dir: Path | None = None) -> None:
        self.project_root = project_root.resolve()
        self.user_config_dir = (user_config_dir or Path.home() / ".paicli-py").resolve()

    def load_for_prompt(self) -> str:
        sections: list[str] = []
        for path, import_root in self._sources():
            if not path.is_file():
                continue
            content = self._read_with_imports(path, import_root, set(), 0).strip()
            if content:
                sections.append(f"### {path}\n\n{content}")
        if not sections:
            return ""
        body = "\n\n".join(sections)
        if len(body) > self.MAX_TOTAL_CHARS:
            keep = max(0, self.MAX_TOTAL_CHARS - 80)
            body = body[:keep].rstrip() + f"\n\n[PAI.md 内容已按 {self.MAX_TOTAL_CHARS} 字符预算截断]"
        return "## PAI.md 项目记忆\n\n" + body

    def _sources(self) -> list[tuple[Path, Path]]:
        return [
            (self.user_config_dir / "PAI.md", self.user_config_dir),
            (self.project_root / "PAI.md", self.project_root),
            (self.project_root / ".paicli" / "PAI.md", self.project_root),
            (self.project_root / "PAI.local.md", self.project_root),
            (self.project_root / ".paicli" / "PAI.local.md", self.project_root),
        ]

    def _read_with_imports(self, path: Path, import_root: Path, stack: set[Path], depth: int) -> str:
        normalized = path.resolve()
        if depth > self.MAX_IMPORT_DEPTH or not normalized.is_relative_to(import_root) or not normalized.is_file():
            logger.warning("Skipping invalid PAI.md import: {}", normalized)
            return ""
        if normalized in stack:
            logger.warning("Skipping cyclic PAI.md import: {}", normalized)
            return ""
        stack.add(normalized)
        try:
            output: list[str] = []
            for line in normalized.read_text(encoding="utf-8").splitlines():
                imported = self._parse_import(line)
                if imported is None:
                    output.append(line)
                else:
                    content = self._read_with_imports(
                        normalized.parent / imported, import_root, stack, depth + 1
                    ).strip()
                    if content:
                        output.append(content)
            return "\n".join(output)
        except OSError as err:
            logger.warning("Failed to read PAI.md {}: {}", normalized, err)
            return ""
        finally:
            stack.remove(normalized)

    @staticmethod
    def _parse_import(line: str) -> str | None:
        stripped = line.strip()
        if not stripped.startswith("@") or len(stripped) < 2 or " " in stripped:
            return None
        candidate = stripped[1:]
        if Path(candidate).is_absolute() or ".." in Path(candidate).parts:
            return None
        return candidate


@dataclass(frozen=True)
class InitResult:
    path: Path
    created: bool
    overwritten: bool


class ProjectMemoryInitializer:
    TEMPLATE = """# PAI.md

## Project

- Describe the project's purpose and supported runtime here.

## Commands

- Build: `<build command>`
- Test: `<test command>`

## Architecture

- Record stable module boundaries and important entry points.

## Pitfalls and don'ts

- Record durable project rules; do not put one-off task notes here.
"""

    @classmethod
    def initialize(cls, root: Path, *, force: bool = False) -> InitResult:
        path = root.resolve() / "PAI.md"
        existed = path.exists()
        if existed and not force:
            return InitResult(path=path, created=False, overwritten=False)
        path.write_text(cls.TEMPLATE, encoding="utf-8")
        return InitResult(path=path, created=not existed, overwritten=existed)
