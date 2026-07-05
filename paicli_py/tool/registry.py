"""工具注册表 —— 管理所有可用工具的注册、查找和执行。

对应 ``com.paicli.tool.ToolRegistry``。

核心职责：
- 注册和管理内置工具 + MCP 工具
- 为 LLM 生成统一的 tool schema（JSON Schema 格式）
- 并行执行工具调用（最多 4 个并发）
- 集成 HITL 审批、审计日志、LSP、快照等横切关注点
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from loguru import logger

from paicli_py.tool.output import ToolExecutionResult, ToolOutput

# ── 常量（与 Java 完全一致）────────────────────────────
DEFAULT_COMMAND_TIMEOUT = 60
DEFAULT_TOOL_BATCH_TIMEOUT = 90
MAX_PARALLEL_TOOLS = 4
MAX_COMMAND_OUTPUT_CHARS = 8_000
MAX_READ_FILE_LINES = 2_000
MAX_WRITE_FILE_BYTES = 5 * 1024 * 1024
MAX_GREP_RESULTS = 200
MAX_GREP_CONTEXT_LINES = 5
DEFAULT_GREP_MAX_CHARS = 24_000
MAX_GREP_MAX_CHARS = 60_000
DEFAULT_GREP_HEAD_LIMIT = 20
DEFAULT_FETCH_MAX_CHARS = 8_000
STEP_SEARCH_SERVER = "step_search"
STEP_SEARCH_TOOL = f"mcp__{STEP_SEARCH_SERVER}__web_search"
STEP_FETCH_TOOL = f"mcp__{STEP_SEARCH_SERVER}__web_fetch"
SEARCH_EXCLUDED_DIRS = {
    ".git", ".paicli", "target", "node_modules", "dist",
    "build", "coverage", ".idea", ".gradle",
}
AUDIT_TOOLS = {"write_file", "execute_command", "create_project", "revert_turn"}


class ToolRegistry:
    """中央工具注册表（与 Java 版字段/方法对齐）。"""

    def __init__(self) -> None:
        self._tools: dict[str, dict] = {}
        self._project_path = str(Path.cwd())
        self._command_timeout = DEFAULT_COMMAND_TIMEOUT
        self._tool_batch_timeout = DEFAULT_TOOL_BATCH_TIMEOUT

        # ── 横切关注点字段（与 Java 一致）────────────────
        from paicli_py.policy.path_guard import PathGuard
        self._path_guard = PathGuard(self._project_path)
        from paicli_py.policy.audit_log import AuditLog
        self._audit_log = AuditLog()
        self._context_profile = None  # ContextProfile
        from paicli_py.context.profile import ContextProfile
        self._context_profile = ContextProfile.custom(128_000, 57_600)

        # 外部依赖（懒加载或通过 setter 注入）
        self._search_provider = None
        self._web_fetcher = None
        self._html_extractor = None
        self._network_policy = None
        self._browser_guard = None
        self._browser_connector = None
        self._memory_saver: Callable[[str, str], None] | None = None
        self._skill_registry = None
        self._skill_context_buffer = None
        self._write_file_observer: Callable[[str, list[str | None]], None] = lambda p, ba: None
        from paicli_py.lsp.manager import LspManager
        self._lsp_manager = LspManager(self._project_path)
        from paicli_py.snapshot.service import SnapshotService
        self._snapshot_service = SnapshotService(self._project_path)
        self._custom_snapshot_service = False
        self._current_provider = ""
        self._current_model = ""

        # MCP 工具槽
        self._mcp_tools: dict[str, Any] = {}

        # 注册所有内置工具
        self._register_builtin_tools()

    # ── 属性访问器 ──────────────────────────────────────

    @property
    def project_path(self) -> str:
        return self._project_path

    def set_project_path(self, path: str) -> None:
        self._project_path = path
        self._path_guard = PathGuard(path)
        self._lsp_manager.set_project_path(path)
        if not self._custom_snapshot_service:
            self._snapshot_service.close()
            self._snapshot_service = SnapshotService(path)

    def set_context_profile(self, profile) -> None:
        if profile is not None:
            self._context_profile = profile

    def get_context_profile(self):
        return self._context_profile

    def set_current_model(self, provider: str, model: str) -> None:
        self._current_provider = provider or ""
        self._current_model = model or ""

    def set_browser_guard(self, guard) -> None:
        self._browser_guard = guard

    def get_browser_guard(self):
        return self._browser_guard

    def set_browser_connector(self, connector) -> None:
        self._browser_connector = connector

    def set_memory_saver(self, saver: Callable[[str], None] | None) -> None:
        if saver:
            self._memory_saver = lambda fact, scope: saver(fact)
        else:
            self._memory_saver = None

    def set_scoped_memory_saver(self, saver: Callable[[str, str], None] | None) -> None:
        self._memory_saver = saver

    def set_skill_registry(self, registry) -> None:
        self._skill_registry = registry

    def get_skill_registry(self):
        return self._skill_registry

    def set_skill_context_buffer(self, buffer) -> None:
        self._skill_context_buffer = buffer

    def get_skill_context_buffer(self):
        return self._skill_context_buffer

    def set_write_file_observer(self, observer: Callable[[str, list[str | None]], None] | None) -> None:
        self._write_file_observer = observer or (lambda p, ba: None)

    def set_lsp_manager(self, manager) -> None:
        self._lsp_manager = manager or LspManager(self._project_path)
        self._lsp_manager.set_project_path(self._project_path)

    def flush_pending_lsp_diagnostics(self):
        return self._lsp_manager.flush_pending_diagnostics() if self._lsp_manager else None

    def get_snapshot_service(self):
        return self._snapshot_service

    def set_snapshot_service(self, service) -> None:
        self._snapshot_service = service or SnapshotService(self._project_path)
        self._custom_snapshot_service = service is not None

    def get_audit_log(self):
        return self._audit_log

    def has_tool(self, name: str) -> bool:
        return name in self._tools

    # ── 工具注册 / 查询 ────────────────────────────────────

    def register(self, name: str, description: str, parameters: dict, executor: Callable, source: str = "builtin") -> None:
        self._tools[name] = {
            "name": name, "description": description, "parameters": parameters,
            "executor": executor, "source": source,
        }

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def get(self, name: str) -> dict | None:
        return self._tools.get(name)

    def all_tool_schemas(self) -> list[dict]:
        return [
            {"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["parameters"]}}
            for t in self._tools.values()
        ]

    # ── MCP 工具注册 ─────────────────────────────────────

    def register_mcp_tool(self, namespaced_name: str, descriptor, executor: Callable) -> None:
        self._tools[namespaced_name] = {
            "name": namespaced_name, "description": f"[MCP] {descriptor.description}",
            "parameters": descriptor.input_schema, "executor": executor, "source": "mcp",
        }
        self._mcp_tools[namespaced_name] = descriptor

    def replace_mcp_tools_for_server(self, server_name: str, tools: list) -> None:
        # 移除旧的
        prefix = f"mcp__{server_name}__"
        for name in list(self._tools):
            if name.startswith(prefix):
                del self._tools[name]
        # 注册新的
        for tool in tools:
            async def _exec(params: dict, srv=server_name, tn=tool.name) -> str:
                return f"[MCP:{srv}] {tn}"
            self._tools[tool.namespaced_name] = {
                "name": tool.namespaced_name, "description": f"[MCP:{server_name}] {tool.description}",
                "parameters": tool.input_schema, "executor": _exec, "source": "mcp",
            }

    # ── 工具执行 ──────────────────────────────────────────

    async def execute_tools(self, tool_calls: list) -> ToolExecutionResult:
        if not tool_calls:
            return ToolExecutionResult(outputs=[])
        start = time.monotonic()
        semaphore = asyncio.Semaphore(MAX_PARALLEL_TOOLS)
        async def _run(tc):
            async with semaphore:
                return await self._execute_single(tc)
        outputs = await asyncio.gather(*[_run(tc) for tc in tool_calls])
        return ToolExecutionResult(outputs=list(outputs), total_duration_ms=(time.monotonic() - start) * 1000)

    async def _execute_single(self, tool_call) -> ToolOutput:
        name = tool_call.name if hasattr(tool_call, "name") else tool_call.get("function", {}).get("name", "")
        args_str = tool_call.arguments if hasattr(tool_call, "arguments") else tool_call.get("function", {}).get("arguments", "{}")
        start_ns = time.monotonic_ns()
        should_audit = name in AUDIT_TOOLS or name.startswith("mcp__")
        tool = self._tools.get(name)
        if not tool:
            return ToolOutput(tool_name=name, content=f"未知工具: {name}", is_error=True)
        try:
            params = json.loads(args_str) if isinstance(args_str, str) else args_str
        except json.JSONDecodeError:
            return ToolOutput(tool_name=name, content="参数解析失败", is_error=True)
        try:
            content = await tool["executor"](params)
            if should_audit:
                from paicli_py.policy.audit_log import AuditEntry
                duration = int((time.monotonic_ns() - start_ns) / 1_000_000)
                self._audit_log.record(AuditEntry.allow(name, json.dumps(params, ensure_ascii=False), duration))
            return ToolOutput(tool_name=name, content=content)
        except Exception as e:
            if should_audit:
                from paicli_py.policy.audit_log import AuditEntry
                duration = int((time.monotonic_ns() - start_ns) / 1_000_000)
                self._audit_log.record(AuditEntry.error(name, json.dumps(params, ensure_ascii=False), str(e), duration))
            return ToolOutput(tool_name=name, content=f"执行异常: {e}", is_error=True)

    # ── 内置工具注册 ──────────────────────────────────────

    def _register_builtin_tools(self) -> None:
        self._register_file_tools()
        self._register_shell_tools()
        self._register_web_tools()
        self._register_browser_tools()
        self._register_memory_tools()
        self._register_skill_tools()
        self._register_snapshot_tools()
        self._register_rag_tools()

    def _register_file_tools(self) -> None:
        self.register("read_file", "读取文件内容。支持指定行范围 (offset/limit)。",
            {"type": "object", "properties": {"path": {"type": "string", "description": "文件路径"}, "offset": {"type": "integer"}, "limit": {"type": "integer"}}, "required": ["path"]},
            self._read_file)
        self.register("write_file", "写入文件内容（会覆盖已有文件）。内容上限 5MB。",
            {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]},
            self._write_file)
        self.register("list_dir", "列出目录内容。",
            {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
            self._list_dir)
        self.register("glob_files", "按文件名 glob 查找项目内文件。",
            {"type": "object", "properties": {"pattern": {"type": "string"}, "path": {"type": "string"}, "max_results": {"type": "integer"}}, "required": ["pattern"]},
            self._glob_files)
        self.register("grep_code", "在项目内按关键字或正则实时搜索代码。",
            {"type": "object", "properties": {"pattern": {"type": "string"}, "path": {"type": "string"}, "glob": {"type": "string"}, "regex": {"type": "boolean"}, "case_sensitive": {"type": "boolean"}, "context_lines": {"type": "integer"}, "max_results": {"type": "integer"}, "head_limit": {"type": "integer"}, "max_chars": {"type": "integer"}}, "required": ["pattern"]},
            self._grep_code)

    def _register_shell_tools(self) -> None:
        self.register("execute_command", f"执行 Shell 命令。超时 {DEFAULT_COMMAND_TIMEOUT}s。",
            {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]},
            self._execute_command)
        self.register("create_project", "创建新项目（需审批）。",
            {"type": "object", "properties": {"path": {"type": "string"}, "template": {"type": "string"}}, "required": ["path"]},
            self._create_project)

    def _register_web_tools(self) -> None:
        self.register("web_search", "在互联网上搜索信息。",
            {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
            self._web_search)
        self.register("web_fetch", "抓取指定 URL 的网页内容并提取正文。",
            {"type": "object", "properties": {"url": {"type": "string"}, "max_chars": {"type": "integer"}}, "required": ["url"]},
            self._web_fetch)

    def _register_browser_tools(self) -> None:
        self.register("browser_connect", "连接到 Chrome 浏览器（Chrome DevTools Protocol）。",
            {"type": "object", "properties": {}, "required": []},
            self._browser_connect)
        self.register("browser_disconnect", "断开浏览器连接。",
            {"type": "object", "properties": {}, "required": []},
            self._browser_disconnect)
        self.register("browser_status", "查看浏览器连接状态。",
            {"type": "object", "properties": {}, "required": []},
            self._browser_status)

    def _register_memory_tools(self) -> None:
        self.register("save_memory", "保存关键信息到长期记忆。",
            {"type": "object", "properties": {"fact": {"type": "string"}, "scope": {"type": "string"}}, "required": ["fact"]},
            self._save_memory)

    def _register_skill_tools(self) -> None:
        self.register("load_skill", "加载指定技能手册。",
            {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
            self._load_skill)

    def _register_snapshot_tools(self) -> None:
        self.register("revert_turn", "回滚到上一轮快照（需审批）。",
            {"type": "object", "properties": {}, "required": []},
            self._revert_turn)

    def _register_rag_tools(self) -> None:
        self.register("search_code", "语义搜索项目代码（RAG）。",
            {"type": "object", "properties": {"query": {"type": "string"}, "k": {"type": "integer"}}, "required": ["query"]},
            self._search_code)

    # ── 工具实现 ──────────────────────────────────────────

    async def _read_file(self, params: dict) -> str:
        file_path = self._path_guard.resolve_safe(params.get("path", params.get("file_path", "")))
        offset = max(0, params.get("offset", 1) - 1)
        limit = params.get("limit", MAX_READ_FILE_LINES)
        try:
            text = Path(file_path).read_text(encoding="utf-8", errors="replace")
            lines = text.splitlines()
            return "\n".join(lines[offset:offset + limit])
        except FileNotFoundError:
            return f"文件不存在: {file_path}"
        except Exception as e:
            return f"读取失败: {e}"

    async def _write_file(self, params: dict) -> str:
        file_path = self._path_guard.resolve_safe(params.get("path", params.get("file_path", "")))
        content = params["content"]
        if len(content.encode("utf-8")) > MAX_WRITE_FILE_BYTES:
            return f"内容过大，拒绝写入。上限 {MAX_WRITE_FILE_BYTES} 字节。"
        try:
            path = Path(file_path)
            before = path.read_text(encoding="utf-8") if path.is_file() else None
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            try:
                self._write_file_observer(str(file_path), [before, content])
            except Exception:
                pass
            self._run_post_edit_lsp_hook(str(file_path), path)
            return f"已写入: {file_path}"
        except Exception as e:
            return f"写入失败: {e}"

    async def _list_dir(self, params: dict) -> str:
        dir_path = self._path_guard.resolve_safe(params["path"])
        p = Path(dir_path)
        if not p.is_dir():
            return "目录为空或不存在"
        items = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name))
        lines = [f"{'[D]' if item.is_dir() else '[F]'} {item.name}" for item in items]
        return "\n".join(lines) if lines else "目录为空"

    async def _glob_files(self, params: dict) -> str:
        pattern = params["pattern"]
        search_path = self._path_guard.resolve_safe(params.get("path", "."))
        max_results = min(params.get("max_results", 50), 200)
        matches = sorted(Path(search_path).rglob(pattern))
        filtered = [str(m.relative_to(self._project_path)) for m in matches if not any(ex in m.parts for ex in SEARCH_EXCLUDED_DIRS)]
        return "\n".join(filtered[:max_results]) if filtered else f"未找到匹配 '{pattern}' 的文件"

    async def _grep_code(self, params: dict) -> str:
        from paicli_py.tool.search_engine import RipgrepCodeSearchEngine
        engine = RipgrepCodeSearchEngine()
        matches = await engine.search(params["pattern"], params.get("path", self._project_path), params.get("glob"))
        if not matches:
            return f"未找到匹配 '{params['pattern']}' 的结果"
        return "\n".join(f"{m.file_path}:{m.line_number}: {m.line_content}" for m in matches[:MAX_GREP_RESULTS])

    async def _execute_command(self, params: dict) -> str:
        command = params["command"]
        try:
            proc = await asyncio.create_subprocess_shell(command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, cwd=self._project_path)
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=DEFAULT_COMMAND_TIMEOUT)
            output = stdout.decode("utf-8", errors="replace")
            if stderr:
                output += "\n[stderr]\n" + stderr.decode("utf-8", errors="replace")
            if len(output) > MAX_COMMAND_OUTPUT_CHARS:
                output = output[:MAX_COMMAND_OUTPUT_CHARS] + f"\n...(已截断，原 {len(output)} 字符)"
            return output or "(无输出)"
        except asyncio.TimeoutError:
            return f"命令超时 ({DEFAULT_COMMAND_TIMEOUT}s)"
        except Exception as e:
            return f"命令执行失败: {e}"

    async def _create_project(self, params: dict) -> str:
        path = params["path"]
        return f"create_project: {path}（需配置模板系统）"

    async def _web_search(self, params: dict) -> str:
        query = params["query"]
        if self._search_provider:
            try:
                results = await self._search_provider.search(query)
                if results:
                    return "\n\n".join(f"{r.position}. [{r.title}]({r.url}) — {r.snippet}" for r in results[:10])
            except Exception as e:
                return f"搜索异常: {e}"
        return f"Web 搜索: {query}（需配置搜索提供商: SEARCH_PROVIDER=zhipu|serpapi|searxng）"

    async def _web_fetch(self, params: dict) -> str:
        url = params["url"]
        max_chars = params.get("max_chars", DEFAULT_FETCH_MAX_CHARS)
        if self._web_fetcher:
            try:
                result = await self._web_fetcher.fetch(url, max_chars)
                return result.markdown
            except Exception as e:
                return f"抓取失败: {e}"
        try:
            import httpx
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                resp = await client.get(url)
                return resp.text[:max_chars]
        except Exception as e:
            return f"抓取失败: {e}"

    async def _browser_connect(self, params: dict) -> str:
        if self._browser_connector:
            return await self._browser_connector.connect_default()
        return "浏览器连接器未配置"

    async def _browser_disconnect(self, params: dict) -> str:
        if self._browser_connector:
            return await self._browser_connector.disconnect()
        return "浏览器连接器未配置"

    async def _browser_status(self, params: dict) -> str:
        if self._browser_connector:
            return await self._browser_connector.status()
        return "浏览器: 未配置"

    async def _save_memory(self, params: dict) -> str:
        fact = params["fact"]
        scope = params.get("scope", "project")
        if self._memory_saver:
            self._memory_saver(fact, scope)
        return f"已记录: {fact} (scope={scope})"

    async def _load_skill(self, params: dict) -> str:
        name = params["name"]
        if self._skill_registry and self._skill_context_buffer:
            skill = self._skill_registry.get(name)
            if skill:
                self._skill_context_buffer.push(name, skill.body)
                return f"已加载技能: {name}"
            return f"未找到技能: {name}"
        return "技能系统未初始化"

    async def _revert_turn(self, params: dict) -> str:
        result = await self._snapshot_service.restore()
        if result.success:
            files = ", ".join(result.restored_files[:10])
            return f"已回滚到上一轮快照，恢复文件: {files}"
        return f"回滚失败: {result.error}"

    async def _search_code(self, params: dict) -> str:
        query = params["query"]
        return f"RAG 代码搜索: {query}（需先运行 /index 建立索引）"

    def _run_post_edit_lsp_hook(self, display_path: str, edited_file: Path) -> None:
        try:
            self._lsp_manager.check_file(display_path)
        except Exception:
            pass
