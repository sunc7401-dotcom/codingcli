from __future__ import annotations

import asyncio
import json
from pathlib import Path

from suncli_py.llm.models import ChatResponse, Message
from suncli_py.memory.commands import run_memory, run_save
from suncli_py.memory.compression import ConversationHistoryCompactor
from suncli_py.memory.manager import MemoryManager
from suncli_py.memory.models import MemoryEntry, MemoryType
from suncli_py.memory.project import ProjectMemoryInitializer, ProjectMemoryLoader
from suncli_py.memory.storage import LongTermMemory


class _FakeClient:
    max_context_window = 128_000

    def __init__(self, responses: list[str] | None = None) -> None:
        self.responses = list(responses or ["摘要"])

    async def chat(self, messages, tools=None, listener=None):
        del messages, tools, listener
        return ChatResponse(role="assistant", content=self.responses.pop(0))


def test_long_term_memory_persists_scopes_and_filters_projects(tmp_path: Path) -> None:
    memory = LongTermMemory(tmp_path)
    memory.store(_entry("global", "默认使用中文", "global"))
    memory.store(_entry("project-a", "项目使用 Java 17", "project", "A"))
    memory.store(_entry("project-b", "项目使用 Python", "project", "B"))
    assert memory.store(_entry("duplicate", "默认使用中文", "project", "A")) is False

    reloaded = LongTermMemory(tmp_path)

    assert [entry.id for entry in reloaded.get_all("A")] == ["project-a", "global"]
    assert [entry.id for entry in reloaded.search("Java", 10, "A")] == ["project-a"]
    assert reloaded.retrieve("global") is not None
    assert reloaded.delete("project-a") is True
    assert LongTermMemory(tmp_path).retrieve("project-a") is None


def test_long_term_memory_ignores_corrupt_json(tmp_path: Path) -> None:
    (tmp_path / "long_term_memory.json").write_text("not-json", encoding="utf-8")

    memory = LongTermMemory(tmp_path)

    assert memory.get_all() == []


def test_memory_manager_injects_project_and_relevant_long_term_memory(tmp_path: Path) -> None:
    (tmp_path / "PAI.md").write_text("- 使用 Maven 验证", encoding="utf-8")
    long_term = LongTermMemory(tmp_path / "memory")
    manager = MemoryManager(_FakeClient(), tmp_path, long_term=long_term, user_config_dir=tmp_path / "user")
    manager.store_fact("这个项目使用 Java 17")
    manager.store_fact("默认用中文回答", "global")

    context = manager.prompt_context("Java 中文")

    assert "使用 Maven 验证" in context
    assert "这个项目使用 Java 17" in context
    assert "默认用中文回答" in context


def test_project_memory_loader_imports_in_order_and_rejects_escape(tmp_path: Path) -> None:
    user = tmp_path / "user"
    project = tmp_path / "project"
    user.mkdir()
    project.mkdir()
    (user / "PAI.md").write_text("user-rule", encoding="utf-8")
    (project / "rules.md").write_text("imported-rule", encoding="utf-8")
    (project / "PAI.md").write_text("@rules.md\n@../outside.md\nproject-rule", encoding="utf-8")
    (tmp_path / "outside.md").write_text("must-not-load", encoding="utf-8")

    context = ProjectMemoryLoader(project, user).load_for_prompt()

    assert context.index("user-rule") < context.index("project-rule")
    assert "imported-rule" in context
    assert "must-not-load" not in context


def test_project_memory_initializer_preserves_existing_file_without_force(tmp_path: Path) -> None:
    path = tmp_path / "PAI.md"
    path.write_text("existing", encoding="utf-8")

    skipped = ProjectMemoryInitializer.initialize(tmp_path)
    overwritten = ProjectMemoryInitializer.initialize(tmp_path, force=True)

    assert skipped.created is False
    assert skipped.overwritten is False
    assert overwritten.overwritten is True
    assert path.read_text(encoding="utf-8").startswith("# PAI.md")


def test_history_compactor_preserves_recent_user_boundary() -> None:
    client = _FakeClient(["旧对话摘要"])
    compactor = ConversationHistoryCompactor(client)
    history = [Message.system("system")]
    for index in range(5):
        history.extend([Message.user(f"question-{index}"), Message.assistant(f"answer-{index}")])

    compacted = asyncio.run(compactor.compact_now(history))

    assert compacted is True
    assert history[0].role == "system"
    assert history[1].content.startswith("[已压缩的历史对话摘要]")
    assert history[-2].content == "question-4"
    assert history[-1].content == "answer-4"


def test_java_compatible_json_field_names(tmp_path: Path) -> None:
    memory = LongTermMemory(tmp_path)
    memory.store(_entry("fact-1", "事实", "global"))

    data = json.loads((tmp_path / "long_term_memory.json").read_text(encoding="utf-8"))

    assert set(data[0]) == {"id", "content", "type", "timestamp", "metadata", "tokenCount"}


def test_scriptable_save_search_and_delete_commands(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("PAICLI_PY_MEMORY_DIR", str(tmp_path / "memory"))
    monkeypatch.chdir(tmp_path)

    assert run_save("项目使用 Java 17") == 0
    assert run_memory("search", "Java") == 0
    search_output = capsys.readouterr().out
    memory_id = next(line.split()[0] for line in search_output.splitlines() if line.startswith("fact-"))
    assert run_memory("delete", memory_id) == 0
    assert LongTermMemory(tmp_path / "memory").get_all() == []


def _entry(entry_id: str, content: str, scope: str, project: str | None = None) -> MemoryEntry:
    metadata = {"scope": scope}
    if project:
        metadata["project"] = project
    return MemoryEntry(id=entry_id, content=content, type=MemoryType.FACT, metadata=metadata)
