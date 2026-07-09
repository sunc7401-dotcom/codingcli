"""Repository-local storage for refactor-agent scan state."""

from __future__ import annotations

import json
from pathlib import Path

from suncli_py.refactor_agent.models import ScanResult


class RefactorAgentStorage:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.base_dir = self.root / ".paicli" / "refactor-agent"

    def save_scan_result(self, result: ScanResult) -> Path:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        output_path = self.base_dir / "issues.json"
        output_path.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return output_path
