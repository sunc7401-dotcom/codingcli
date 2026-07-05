"""审批结果 —— 对应 ``com.paicli.hitl.ApprovalResult`` record。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ApprovalDecision(Enum):
    APPROVED = "APPROVED"
    APPROVED_ALL = "APPROVED_ALL"
    APPROVED_ALL_BY_SERVER = "APPROVED_ALL_BY_SERVER"
    REJECTED = "REJECTED"
    MODIFIED = "MODIFIED"
    SKIPPED = "SKIPPED"


@dataclass(frozen=True)
class ApprovalResult:
    decision: ApprovalDecision
    modified_arguments: str | None = None
    reason: str | None = None

    @classmethod
    def approve(cls) -> ApprovalResult:
        return cls(ApprovalDecision.APPROVED)

    @classmethod
    def approve_all(cls) -> ApprovalResult:
        return cls(ApprovalDecision.APPROVED_ALL)

    @classmethod
    def approve_all_by_server(cls) -> ApprovalResult:
        return cls(ApprovalDecision.APPROVED_ALL_BY_SERVER)

    @classmethod
    def reject(cls, reason: str = "") -> ApprovalResult:
        return cls(ApprovalDecision.REJECTED, reason=reason)

    @classmethod
    def modify(cls, modified_arguments: str) -> ApprovalResult:
        return cls(ApprovalDecision.MODIFIED, modified_arguments=modified_arguments)

    @classmethod
    def skip(cls) -> ApprovalResult:
        return cls(ApprovalDecision.SKIPPED)

    @property
    def is_approved(self) -> bool:
        return self.decision in (ApprovalDecision.APPROVED, ApprovalDecision.APPROVED_ALL, ApprovalDecision.APPROVED_ALL_BY_SERVER, ApprovalDecision.MODIFIED)

    @property
    def is_approved_all(self) -> bool:
        return self.decision == ApprovalDecision.APPROVED_ALL

    @property
    def is_approved_all_for_tool(self) -> bool:
        return self.is_approved_all

    @property
    def is_approved_all_for_server(self) -> bool:
        return self.decision == ApprovalDecision.APPROVED_ALL_BY_SERVER

    @property
    def is_rejected(self) -> bool:
        return self.decision == ApprovalDecision.REJECTED

    @property
    def is_skipped(self) -> bool:
        return self.decision == ApprovalDecision.SKIPPED

    def effective_arguments(self, original: str) -> str:
        """如果是 MODIFIED 则返回修改后的参数，否则返回原始参数。"""
        if self.decision == ApprovalDecision.MODIFIED and self.modified_arguments:
            return self.modified_arguments
        return original
