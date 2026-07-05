"""运行时事件模型。

对应 ``com.paicli.runtime.api.RuntimeEvent``。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass
class RuntimeEvent:
    """SSE 流中的事件数据载体。"""
    id: int
    thread_id: str
    type: str  # thread.created | turn.started | message.delta | turn.completed | turn.failed
    data: str
    created_at: datetime = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now(UTC)
