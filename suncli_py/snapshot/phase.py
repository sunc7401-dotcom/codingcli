"""快照阶段枚举 —— 与 Java 值完全一致（小写 label）。

对应 ``com.paicli.snapshot.SnapshotPhase``。
"""

from enum import Enum


class SnapshotPhase(str, Enum):
    PRE_TURN = "pre-turn"
    POST_TURN = "post-turn"
    PRE_RESTORE = "pre-restore"
