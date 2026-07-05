"""快照配置。

对应 ``com.paicli.snapshot.SnapshotConfig``。
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path


class SnapshotConfig:
    """侧 Git 快照系统配置。

    配置来源：环境变量 > 默认值。
    """

    @staticmethod
    def enabled() -> bool:
        """是否启用快照（PAICLI_SNAPSHOT_ENABLED=true 时启用）。"""
        return os.environ.get("PAICLI_SNAPSHOT_ENABLED", "").lower() in ("true", "1", "yes")

    @staticmethod
    def snapshots_root() -> Path:
        """快照存储根目录。"""
        custom = os.environ.get("PAICLI_SNAPSHOTS_ROOT", "")
        if custom:
            return Path(custom)
        return Path.home() / ".paicli" / "snapshots"

    @staticmethod
    def max_snapshots() -> int:
        """每个项目最多保留的快照数。"""
        try:
            return int(os.environ.get("PAICLI_MAX_SNAPSHOTS", "50"))
        except ValueError:
            return 50

    @staticmethod
    def project_key(project_path: str) -> str:
        """生成项目唯一标识（SHA-256 前 12 位）。"""
        return hashlib.sha256(project_path.encode()).hexdigest()[:12]

    @staticmethod
    def excludes() -> list[str]:
        """不需要快照的文件模式。"""
        return [
            ".git", ".paicli", "node_modules", "__pycache__",
            "*.pyc", ".venv", "venv", "target", "build", "dist",
        ]
