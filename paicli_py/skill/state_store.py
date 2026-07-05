"""技能状态持久化 —— 对应 ``com.paicli.skill.SkillStateStore``。"""

from __future__ import annotations

import json
from pathlib import Path


class SkillStateStore:
    """持久化技能的启用/禁用状态。"""

    DEFAULT_FILE: Path = Path.home() / ".paicli" / "skills.json"

    def __init__(self, file_path: Path | None = None) -> None:
        self._file = file_path or self.DEFAULT_FILE

    @property
    def file(self) -> Path:
        return self._file

    def disabled(self) -> set[str]:
        """每次调用从文件重新读取（与 Java 一致）。"""
        if not self._file.is_file():
            return set()
        try:
            data = json.loads(self._file.read_text(encoding="utf-8"))
            return set(data.get("disabled", []))
        except (json.JSONDecodeError, KeyError):
            return set()

    def enable(self, name: str) -> None:
        current = self.disabled()
        current.discard(name)
        self._save(current)

    def disable(self, name: str) -> None:
        current = self.disabled()
        current.add(name)
        self._save(current)

    def _save(self, disabled: set[str]) -> None:
        self._file.parent.mkdir(parents=True, exist_ok=True)
        self._file.write_text(json.dumps({"disabled": list(disabled)}, ensure_ascii=False, indent=2), encoding="utf-8")
