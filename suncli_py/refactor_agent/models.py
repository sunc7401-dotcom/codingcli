"""Data models for the Java refactor-agent MVP."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class MavenModule:
    """Detected Maven module metadata."""

    name: str
    path: str
    has_main_java: bool
    has_test_java: bool


@dataclass(frozen=True)
class ProjectProfile:
    """Project profile produced by the phase-one detector."""

    root: Path
    is_git_repo: bool
    is_maven_project: bool
    has_main_java: bool
    has_test_java: bool
    is_git_clean: bool
    maven_version: str | None = None
    java_version: str | None = None
    modules: list[MavenModule] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["root"] = str(self.root)
        return data


class SmellType(StrEnum):
    LONG_METHOD = "long_method"
    LARGE_CLASS = "large_class"
    COMPLEX_CONDITION = "complex_condition"
    DUPLICATE_CODE = "duplicate_code"
    DEAD_CODE = "dead_code"
    UNCLEAR_NAMING = "unclear_naming"


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RefactoringType(StrEnum):
    EXTRACT_METHOD = "Extract Method"
    EXTRACT_CLASS = "Extract Class"
    INTRODUCE_EXPLAINING_VARIABLE = "Introduce Explaining Variable"
    REPLACE_DUPLICATE_LOGIC = "Replace Duplicate Logic With Shared Method"
    REMOVE_DEAD_CODE = "Remove Dead Code"
    RENAME = "Rename Variable / Method / Class"


@dataclass(frozen=True)
class Evidence:
    message: str
    metrics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RefactorIssue:
    id: str
    type: SmellType
    severity: Severity
    file_path: str
    symbol: str | None
    start_line: int
    end_line: int
    evidence: list[Evidence]
    impact: str
    recommendation: str
    suggested_refactoring: RefactoringType
    auto_applicable: bool
    risk_level: RiskLevel
    requires_review: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ScanResult:
    profile: ProjectProfile
    issues: list[RefactorIssue]
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile": self.profile.to_dict(),
            "issues": [issue.to_dict() for issue in self.issues],
            "warnings": self.warnings,
        }
