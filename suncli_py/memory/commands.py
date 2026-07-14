"""Scriptable command handlers for long-term and project memory."""

from __future__ import annotations

import uuid
from pathlib import Path

from suncli_py.memory.models import MemoryEntry, MemoryType
from suncli_py.memory.project import ProjectMemoryInitializer
from suncli_py.memory.storage import LongTermMemory


def run_memory(action: str, value: str | None = None) -> int:
    memory = LongTermMemory()
    project_key = str(Path(".").resolve())
    if action == "status":
        print(f"长期记忆: {len(memory.get_all())}条 / {memory.token_count} tokens")
        return 0
    if action == "list":
        _print_entries(memory, memory.get_all())
        return 0
    if action == "search":
        if not value or not value.strip():
            print("error: memory search requires a query")
            return 2
        _print_entries(memory, memory.search(value, 20, project_key))
        return 0
    if action == "delete":
        if not value:
            print("error: memory delete requires an id")
            return 2
        if not memory.delete(value):
            print(f"Memory not found: {value}")
            return 1
        print(f"Deleted: {value}")
        return 0
    if action == "clear":
        memory.clear()
        print("Long-term memory cleared.")
        return 0
    return 2


def run_save(fact: str, *, global_scope: bool = False) -> int:
    normalized = fact.strip()
    if not normalized:
        print("error: fact cannot be empty")
        return 2
    metadata = {"source": "fact", "scope": "global" if global_scope else "project"}
    if not global_scope:
        metadata["project"] = str(Path(".").resolve())
    memory = LongTermMemory()
    entry = MemoryEntry(
        id=f"fact-{uuid.uuid4().hex[:8]}", content=normalized, type=MemoryType.FACT, metadata=metadata
    )
    stored = memory.store(entry)
    if stored:
        print(f"Saved to long-term memory({metadata['scope']}): {normalized}")
    else:
        print("An identical memory already exists; nothing was changed.")
    return 0


def run_init(*, force: bool = False) -> int:
    result = ProjectMemoryInitializer.initialize(Path("."), force=force)
    if result.created:
        print(f"Created {result.path}")
    elif result.overwritten:
        print(f"Overwrote {result.path}")
    else:
        print(f"Skipped existing {result.path}; use --force to overwrite")
    return 0


def _print_entries(memory: LongTermMemory, entries: list[MemoryEntry]) -> None:
    if not entries:
        print("No matching long-term memory.")
        return
    for entry in entries:
        print(f"{entry.id} [{memory.scope_of(entry)}] {entry.content}")
