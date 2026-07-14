"""In-memory conversation storage and JSON-backed long-term storage."""

from __future__ import annotations

import importlib
import json
import os
import re
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any

from loguru import logger

from suncli_py.memory.models import MemoryEntry

try:
    jieba: Any = importlib.import_module("jieba")
except ImportError:  # pragma: no cover - fallback supports source checkouts before dependency sync
    jieba = None


def tokenize(text: str) -> set[str]:
    normalized = text.strip().lower()
    if not normalized:
        return set()
    words = set(re.findall(r"[a-z0-9_.$-]+", normalized))
    chinese_chunks = re.findall(r"[\u4e00-\u9fff]+", normalized)
    if jieba is not None:
        words.update(token.strip() for token in jieba.cut(normalized) if token.strip())
    else:
        for chunk in chinese_chunks:
            words.add(chunk)
            words.update(chunk[index : index + 2] for index in range(max(0, len(chunk) - 1)))
    return {word for word in words if word}


class ConversationMemory:
    def __init__(self, max_tokens: int) -> None:
        self.max_tokens = max(1, max_tokens)
        self._entries: OrderedDict[str, MemoryEntry] = OrderedDict()
        self._tokens = 0

    def store(self, entry: MemoryEntry) -> None:
        previous = self._entries.pop(entry.id, None)
        if previous:
            self._tokens -= previous.token_count
        self._entries[entry.id] = entry
        self._tokens += entry.token_count

    def replace_with_summary(self, entry: MemoryEntry) -> None:
        self.clear()
        self.store(entry)

    def get_all(self) -> list[MemoryEntry]:
        return list(self._entries.values())

    def clear(self) -> None:
        self._entries.clear()
        self._tokens = 0

    @property
    def token_count(self) -> int:
        return self._tokens


class LongTermMemory:
    STORAGE_FILE = "long_term_memory.json"

    def __init__(self, storage_dir: Path | None = None) -> None:
        configured = os.environ.get("PAICLI_PY_MEMORY_DIR", "").strip()
        directory = storage_dir or (
            Path(configured).expanduser() if configured else Path.home() / ".paicli-py" / "memory"
        )
        self.storage_file = directory.resolve() / self.STORAGE_FILE
        self._entries: dict[str, MemoryEntry] = {}
        self._lock = threading.RLock()
        self._load()

    def store(self, entry: MemoryEntry) -> bool:
        with self._lock:
            if any(existing.content == entry.content for existing in self._entries.values()):
                return False
            self._entries[entry.id] = entry
            self._save()
            return True

    def retrieve(self, entry_id: str) -> MemoryEntry | None:
        return self._entries.get(entry_id)

    def get_all(self, project_key: str | None = None) -> list[MemoryEntry]:
        entries = list(self._entries.values())
        if project_key is not None:
            entries = [entry for entry in entries if self.is_visible(entry, project_key)]
        return sorted(entries, key=lambda entry: entry.timestamp, reverse=True)

    def search(self, query: str, limit: int, project_key: str | None = None) -> list[MemoryEntry]:
        query_tokens = tokenize(query)
        matches = []
        for entry in self.get_all(project_key):
            haystacks = [entry.content, *entry.metadata.values()]
            if any(query.lower() in value.lower() for value in haystacks) or any(
                token in value.lower() for token in query_tokens for value in haystacks
            ):
                matches.append(entry)
        return matches[: max(0, limit)]

    def delete(self, entry_id: str) -> bool:
        with self._lock:
            if self._entries.pop(entry_id, None) is None:
                return False
            self._save()
            return True

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._save()

    @property
    def token_count(self) -> int:
        return sum(entry.token_count for entry in self._entries.values())

    @staticmethod
    def scope_of(entry: MemoryEntry) -> str:
        return "project" if entry.metadata.get("scope", "").lower() == "project" else "global"

    @classmethod
    def is_visible(cls, entry: MemoryEntry, project_key: str | None) -> bool:
        if cls.scope_of(entry) == "global":
            return True
        return bool(project_key and entry.metadata.get("project") == project_key)

    def _load(self) -> None:
        if not self.storage_file.is_file():
            return
        try:
            raw = json.loads(self.storage_file.read_text(encoding="utf-8"))
            if not isinstance(raw, list):
                raise ValueError("memory file root must be a JSON array")
            for item in raw:
                if not isinstance(item, dict):
                    continue
                try:
                    entry = MemoryEntry.from_dict(item)
                except (KeyError, TypeError, ValueError):
                    continue
                self._entries[entry.id] = entry
        except (OSError, ValueError, json.JSONDecodeError) as err:
            logger.warning("Failed to load long-term memory {}: {}", self.storage_file, err)

    def _save(self) -> None:
        try:
            self.storage_file.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.storage_file.with_suffix(".json.tmp")
            data = [entry.to_dict() for entry in self.get_all()]
            temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            temporary.replace(self.storage_file)
        except OSError as err:
            logger.warning("Failed to persist long-term memory {}: {}", self.storage_file, err)
