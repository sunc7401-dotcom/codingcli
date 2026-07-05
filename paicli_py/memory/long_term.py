"""长期记忆 —— JSON 文件持久化。

对应 ``com.paicli.memory.LongTermMemory``。

存储路径可配置: PAICLI_MEMORY_DIR 环境变量 或 ~/.paicli/memory/
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import ClassVar

from paicli_py.memory.memory_entry import MemoryEntry, MemoryType
from paicli_py.memory.protocol import Memory
from paicli_py.memory.query_tokenizer import matches, tokenize


class LongTermMemory(Memory):
    """基于 JSON 文件的长期记忆存储。

    特性：
    - 自动去重（基于内容精确匹配）
    - 按项目范围过滤
    - 关键词搜索 + 元数据匹配
    - 可配置存储目录
    """

    @staticmethod
    def _resolve_storage_dir() -> Path:
        """存储目录: PAICLI_MEMORY_DIR > ~/.paicli/memory"""
        custom = os.environ.get("PAICLI_MEMORY_DIR", "")
        if custom:
            return Path(custom)
        return Path.home() / ".paicli" / "memory"

    STORAGE_DIR: ClassVar[Path] = Path.home() / ".paicli" / "memory"
    STORAGE_FILE_NAME: ClassVar[str] = "long_term_memory.json"

    def __init__(self, storage_dir: Path | None = None) -> None:
        self._storage_dir = storage_dir or self._resolve_storage_dir()
        self._storage_file = self._storage_dir / self.STORAGE_FILE_NAME
        self._entries: dict[str, MemoryEntry] = {}
        self._token_counter: int = 0  # 增量追踪，避免每次遍历全部
        self._load()

    # ── Memory 协议实现 ──────────────────────────────────────

    def store(self, entry: MemoryEntry) -> None:
        """存储条目（去重：相同内容不重复存储）。"""
        for existing in self._entries.values():
            if existing.content == entry.content:
                # 更新 token 计数：替换旧条目
                self._token_counter -= existing.token_count
                self._token_counter += entry.token_count
                self._entries[entry.id] = entry
                self._save()
                return

        self._entries[entry.id] = entry
        self._token_counter += entry.token_count
        self._save()

    def retrieve(self, entry_id: str) -> MemoryEntry | None:
        return self._entries.get(entry_id)

    def search(self, query: str, limit: int, project_key: str | None = None) -> list[MemoryEntry]:
        """关键词搜索（匹配 content + metadata.values()），按项目过滤。"""
        tokens = tokenize(query)
        results: list[MemoryEntry] = []

        for entry in self._entries.values():
            # 项目范围过滤
            if project_key and not self._is_visible_in_project(entry, project_key):
                continue
            # 匹配 content 或 metadata 值
            search_text = entry.content + " " + " ".join(str(v) for v in entry.metadata.values())
            if matches(search_text, tokens):
                results.append(entry)

        return results[:limit]

    def get_all(self, project_key: str | None = None) -> list[MemoryEntry]:
        """获取全部条目（可选按项目过滤）。"""
        if project_key is None:
            return list(self._entries.values())
        return [e for e in self._entries.values() if self._is_visible_in_project(e, project_key)]

    def get_by_type(self, mem_type: MemoryType) -> list[MemoryEntry]:
        """按类型获取条目。"""
        return [e for e in self._entries.values() if e.type == mem_type]

    def delete(self, entry_id: str) -> bool:
        removed = self._entries.pop(entry_id, None)
        if removed:
            self._token_counter -= removed.token_count
            self._save()
            return True
        return False

    def clear(self) -> None:
        self._entries.clear()
        self._token_counter = 0
        self._save()

    @property
    def token_count(self) -> int:
        return self._token_counter

    def size(self) -> int:
        return len(self._entries)

    @property
    def storage_file(self) -> Path:
        return self._storage_file

    # ── 工具方法 ──────────────────────────────────────────

    @staticmethod
    def is_visible_in_project(entry: MemoryEntry, project_key: str) -> bool:
        """判断条目在指定项目中是否可见。"""
        return LongTermMemory._is_visible_in_project(entry, project_key)

    @staticmethod
    def scope_of(entry: MemoryEntry) -> str:
        """获取条目的范围（global/project）。"""
        return entry.metadata.get("scope", "project")

    @staticmethod
    def _is_visible_in_project(entry: MemoryEntry, project_key: str) -> bool:
        scope = entry.metadata.get("scope", "project")
        if scope == "global":
            return True
        entry_project = entry.metadata.get("project", "")
        return entry_project == project_key

    def get_status_summary(self) -> str:
        """按类型统计的状态摘要。"""
        facts = len(self.get_by_type(MemoryType.FACT))
        summaries = len(self.get_by_type(MemoryType.SUMMARY))
        tool_results = len(self.get_by_type(MemoryType.TOOL_RESULT))
        conversations = len(self.get_by_type(MemoryType.CONVERSATION))
        parts: list[str] = []
        if facts: parts.append(f"事实: {facts}")
        if summaries: parts.append(f"摘要: {summaries}")
        if tool_results: parts.append(f"工具结果: {tool_results}")
        if conversations: parts.append(f"对话: {conversations}")
        type_str = ", ".join(parts) if parts else "空"
        return f"长期记忆: {len(self._entries)}条 ({type_str}) / {self._token_counter} tokens"

    # ── 持久化 ──────────────────────────────────────────────

    def _load(self) -> None:
        if not self._storage_file.is_file():
            return
        try:
            data = json.loads(self._storage_file.read_text(encoding="utf-8"))
            for item in data:
                entry = MemoryEntry(
                    id=item["id"],
                    content=item["content"],
                    type=MemoryType(item.get("type", "FACT")),
                    timestamp=item.get("timestamp", 0),
                    metadata=item.get("metadata", {}),
                    token_count=item.get("token_count", item.get("tokenCount", MemoryEntry.estimate_tokens(item.get("content", "")))),
                )
                self._entries[entry.id] = entry
                self._token_counter += entry.token_count
        except (json.JSONDecodeError, KeyError):
            pass

    def _save(self) -> None:
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        data = [{
            "id": e.id, "content": e.content, "type": e.type.value,
            "timestamp": e.timestamp, "metadata": e.metadata, "tokenCount": e.token_count,
        } for e in self._entries.values()]
        self._storage_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
