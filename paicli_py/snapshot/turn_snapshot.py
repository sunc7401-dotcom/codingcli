"""轮次快照模型 —— 对应 ``com.paicli.snapshot.TurnSnapshot``。"""

from __future__ import annotations

from dataclasses import dataclass

from paicli_py.snapshot.phase import SnapshotPhase


@dataclass
class TurnSnapshot:
    commit_id: str
    phase: SnapshotPhase
    turn_id: str
    created_at: str = ""
    summary: str = ""
