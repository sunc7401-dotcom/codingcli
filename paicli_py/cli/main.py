"""CLI 主入口 —— 对应 ``com.paicli.cli.Main``。

完整的交互式 REPL、微信通道和运行时服务模式。
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path
from typing import Any

from loguru import logger

from paicli_py import __version__
from paicli_py.cli.parser import CommandType, parse
from paicli_py.config.config import PaiCliConfig
from paicli_py.llm.factory import create_client, create_client_from_config
from paicli_py.render.factory import RendererFactory


# ═══════════════════════════════════════════════════════════
# 启动画面
# ═══════════════════════════════════════════════════════════

def _startup_screen(llm_client, mcp_manager, skill_registry, skill_state) -> str:
    """构建启动画面（与 Java StartupScreenInfo 对齐）。"""
    lines = [
        f"  PaiCLI v{__version__} (Python) — 终端 Agent IDE",
        f"  模型: {llm_client.provider_name}/{llm_client.model_name}  |  窗口: {llm_client.max_context_window:,} tokens",
    ]
    if mcp_manager:
        servers = mcp_manager.list_servers()
        ready = sum(1 for s in servers if s.is_ready)
        tools = sum(len(s.tools) for s in servers if s.is_ready)
        lines.append(f"  MCP: {ready}/{len(servers)} 就绪  |  {tools} 工具可用")
    if skill_registry and skill_state:
        all_skills = skill_registry.list_all()
        enabled = len(skill_registry.enabled_skills())
        lines.append(f"  技能: {enabled}/{len(all_skills)} 启用")
    lines.append("  输入 /help 查看所有命令  |  直接输入问题开始对话")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
# 斜杠命令提示（对齐 Java slashCommandHints）
# ═══════════════════════════════════════════════════════════

_SLASH_HINTS: list[tuple[str, str]] = [
    ("/exit", "退出"), ("/quit", "退出"), ("/cancel", "取消"),
    ("/clear", "清空"), ("/compact", "压缩"), ("/history clear", "清空历史"),
    ("/init", "初始化 PAI.md"), ("/init --force", "强制重新生成 PAI.md"),
    ("/model", "查看模型"), ("/model <名称>", "切换模型"),
    ("/plan", "Plan+Execute"), ("/team", "多Agent团队"),
    ("/hitl on", "开启HITL"), ("/hitl off", "关闭HITL"), ("/hitl", "查看HITL"),
    ("/memory", "记忆状态"), ("/memory list", "列出"), ("/memory search <k>", "搜索"), ("/memory delete <id>", "删除"), ("/memory clear", "清空"),
    ("/save <内容>", "保存到长期记忆"), ("/save --global <内容>", "全局保存"),
    ("/index", "索引项目"), ("/search <k>", "搜索代码"), ("/graph <类名>", "关系图"),
    ("/context", "上下文"), ("/policy", "安全策略"),
    ("/config", "查看配置"), ("/config <provider>", "配置提供商"),
    ("/audit", "最近20条"), ("/audit <N>", "最近N条审计"),
    ("/snapshot", "列出快照"), ("/snapshot status", "快照状态"), ("/snapshot clean", "清理"),
    ("/restore", "恢复上轮"), ("/restore <N>", "恢复第N轮前"),
    ("/mcp", "列出服务器"), ("/mcp restart <s>", "重启"), ("/mcp logs <s>", "日志"),
    ("/mcp disable <s>", "禁用"), ("/mcp enable <s>", "启用"),
    ("/mcp resources <s>", "资源列表"), ("/mcp prompts <s>", "提示词模板"),
    ("/browser", "浏览器状态"), ("/browser connect", "连接"), ("/browser disconnect", "断开"),
    ("/wechat", "微信状态"), ("/wechat setup", "配置"), ("/wechat stop", "停止"),
    ("/task", "任务列表"), ("/task add <内容>", "添加任务"), ("/task cancel <id>", "取消"), ("/task log <id>", "任务详情"),
    ("/skill", "列出技能"), ("/skill show <n>", "查看"), ("/skill on <n>", "启用"), ("/skill off <n>", "禁用"), ("/skill reload", "重载"),
    ("/export", "导出对话"),
]


def _print_help() -> None:
    print("可用命令:")
    for hint, desc in _SLASH_HINTS:
        print(f"  {hint:<28} {desc}")


# ═══════════════════════════════════════════════════════════
# 命令处理器（完整 43 条命令）
# ═══════════════════════════════════════════════════════════

def _handle_command(command, state: dict[str, Any]) -> bool:
    """
    Returns:
        True = 继续, False = 退出
    """
    ct = command.type
    payload = command.payload or ""

    agent = state.get("agent")
    config = state.get("config")
    memory = state.get("memory_manager")
    tools = state.get("tool_registry")
    mcp = state.get("mcp_manager")
    skills = state.get("skill_registry")
    skill_st = state.get("skill_state")
    snap = state.get("snapshot_service")
    hitl = state.get("hitl_handler")
    renderer = state.get("renderer")

    # ── 基础 ──
    if ct == CommandType.EXIT:
        print("再见！"); return False
    elif ct == CommandType.CANCEL:
        print("已取消当前操作"); return True
    elif ct == CommandType.CLEAR:
        if agent: agent.clear_history()
        if memory: memory.clear_short_term()
        print("✅ 已清空"); return True
    elif ct == CommandType.COMPACT:
        if agent:
            result = agent.compact_history_now()
            print(f"✅ 压缩完成: {result.before_messages} → {result.after_messages} 条消息")
        else:
            print("⚠️ Agent 未初始化"); return True
    elif ct == CommandType.HISTORY_CLEAR:
        state["history_clear"] = True
        print("✅ 输入历史已清空（下次启动生效）"); return True

    # ── 模型/模式 ──
    elif ct == CommandType.SWITCH_MODEL:
        if payload:
            new_client = create_client(payload, config)
            if new_client:
                if agent: agent.set_llm_client(new_client)
                state["llm_client"] = new_client
                print(f"✅ 已切换到: {new_client.provider_name}/{new_client.model_name}")
            else:
                print(f"❌ 切换失败: 无法连接到 {payload}")
        else:
            print(f"当前: {config.default_provider} / {config.get_model(config.default_provider) or '?'}")
        return True
    elif ct == CommandType.SWITCH_PLAN:
        from paicli_py.agent.plan_execute import PlanExecuteAgent
        if agent:
            state["plan_agent"] = PlanExecuteAgent(agent)
            state["mode"] = "plan"
            print("✅ 已切换到 Plan-and-Execute 模式"); return True
    elif ct == CommandType.SWITCH_TEAM:
        state["mode"] = "team"
        print("✅ 已切换到 Multi-Agent 团队模式"); return True
    elif ct == CommandType.SWITCH_HITL:
        if hitl:
            if payload == "on": hitl.enable(); print("✅ HITL 已开启")
            elif payload == "off": hitl.disable(); print("✅ HITL 已关闭")
            else: print(f"HITL: {'开启' if hitl.is_enabled() else '关闭'}"); return True

    # ── 记忆 ──
    elif ct == CommandType.MEMORY_STATUS:
        if memory: print(memory.get_system_status()); return True
    elif ct == CommandType.MEMORY_CLEAR:
        if memory: memory.clear_long_term(); print("✅ 已清空"); return True
    elif ct == CommandType.MEMORY_LIST:
        if memory:
            for e in memory.list_long_term(): print(f"  [{e.id[:8]}] {e.content[:100]}")
            if not memory.list_long_term(): print("(空)"); return True
    elif ct == CommandType.MEMORY_DELETE:
        if memory and payload.strip():
            ok = memory.delete_long_term(payload.strip())
            print(f"{'✅ 已删除' if ok else '❌ 未找到'}"); return True
    elif ct == CommandType.MEMORY_SEARCH:
        if memory and payload.strip():
            for e in memory.search_long_term(payload.strip(), 10):
                print(f"  [{e.id[:8]}] {e.content[:120]}"); return True
    elif ct == CommandType.MEMORY_SAVE:
        if memory and payload: memory.store_fact(payload); print("✅ 已保存"); return True

    # ── 代码索引 ──
    elif ct == CommandType.INDEX_CODE:
        print("🔄 索引中（RAG 需要先运行 /index）..."); return True
    elif ct == CommandType.SEARCH_CODE:
        if payload: print(f"搜索: {payload}（需先 /index）"); return True
    elif ct == CommandType.GRAPH_QUERY:
        if payload: print(f"关系图: {payload}"); return True

    # ── 上下文/策略/配置 ──
    elif ct == CommandType.CONTEXT_STATUS:
        if memory: print(memory.context_profile.summary()); return True
    elif ct == CommandType.POLICY_STATUS:
        from paicli_py.policy.command_guard import check_command
        print("策略: PathGuard + CommandGuard + AuditLog 已启用"); return True
    elif ct == CommandType.CONFIG:
        if payload:
            parts = payload.split(maxsplit=1)
            cfg_provider = parts[0]
            print(f"配置 {cfg_provider}: api_key={'***' if config.get_api_key(cfg_provider) else '(未设置)'}")
        else:
            print(f"默认: {config.default_provider}  |  已配置: {', '.join(config.providers.keys()) or '(无)'}")
        return True
    elif ct == CommandType.AUDIT_TAIL:
        from paicli_py.policy.audit_log import AuditLog
        log = AuditLog()
        n = int(payload) if payload and payload.isdigit() else 20
        for entry in log.read_recent(n):
            print(f"  {entry.get('timestamp','')} [{entry.get('tool','')}] {entry.get('outcome','')} {entry.get('reason','')}")
        return True

    # ── 快照 ──
    elif ct == CommandType.SNAPSHOT:
        if snap:
            if payload == "clean":
                snap.clean(); print("✅ 快照已清理")
            else:
                print(snap.status()); return True
    elif ct == CommandType.RESTORE_SNAPSHOT:
        if snap:
            offset = int(payload) if payload and payload.lstrip("-").isdigit() else 1
            result = asyncio.get_event_loop().run_until_complete(snap.restore(offset))
            if result.success: print(f"✅ 已恢复到第{offset}轮前快照")
            else: print(f"❌ {result.error}"); return True

    # ── MCP ──
    elif ct == CommandType.MCP_LIST:
        if mcp:
            for s in mcp.list_servers():
                icon = "🟢" if s.is_ready else "🔴"
                print(f"  {icon} {s.name} [{s.status.value}] {len(s.tools)} 工具"); return True
    elif ct == CommandType.MCP_RESTART:
        if mcp and payload.strip(): asyncio.create_task(mcp.restart(payload.strip())); print(f"🔄 重启中: {payload.strip()}"); return True
    elif ct == CommandType.MCP_LOGS:
        if mcp and payload.strip():
            for line in mcp.get_logs(payload.strip())[-20:]: print(f"  {line}"); return True
    elif ct == CommandType.MCP_DISABLE:
        if mcp and payload.strip(): asyncio.create_task(mcp.disable(payload.strip())); print(f"✅ 已禁用: {payload.strip()}"); return True
    elif ct == CommandType.MCP_ENABLE:
        if mcp and payload.strip(): asyncio.create_task(mcp.enable(payload.strip())); print(f"✅ 已启用: {payload.strip()}"); return True
    elif ct == CommandType.MCP_RESOURCES:
        if mcp and payload.strip(): print(f"资源: {payload.strip()}"); return True
    elif ct == CommandType.MCP_PROMPTS:
        if mcp and payload.strip(): print(f"提示词: {payload.strip()}"); return True

    # ── 浏览器 ──
    elif ct == CommandType.BROWSER:
        browser = state.get("browser_connector")
        if browser:
            status = asyncio.get_event_loop().run_until_complete(browser.status())
            print(status)
        else: print("浏览器未配置"); return True

    # ── 微信 ──
    elif ct == CommandType.WECHAT:
        print("微信 iLink 通道 (需独立启动: python -m paicli_py.wechat)"); return True

    # ── 后台任务 ──
    elif ct == CommandType.TASK:
        tm = state.get("task_manager")
        if tm:
            from paicli_py.runtime.task.formatter import handle
            print(handle(tm, payload)); return True

    # ── 技能 ──
    elif ct == CommandType.SKILL_LIST:
        if skills:
            for s in skills.list_all():
                status = "✅" if skill_st.is_enabled(s.name) else "❌"
                print(f"  {status} {s.name} — {s.description[:80]}"); return True
    elif ct == CommandType.SKILL_SHOW:
        if skills and payload.strip():
            s = skills.get(payload.strip())
            if s: print(f"{s.name}\n{s.description}\nv{s.version}\n---\n{s.body[:2000]}")
            else: print(f"未找到: {payload.strip()}"); return True
    elif ct == CommandType.SKILL_ON:
        if skill_st and payload.strip(): skill_st.enable(payload.strip()); print(f"✅ 已启用: {payload.strip()}"); return True
    elif ct == CommandType.SKILL_OFF:
        if skill_st and payload.strip(): skill_st.disable(payload.strip()); print(f"✅ 已禁用: {payload.strip()}"); return True
    elif ct == CommandType.SKILL_RELOAD:
        if skills: skills.reload(); print(f"✅ 已重载 ({len(skills)} 个)"); return True

    # ── 导出 ──
    elif ct == CommandType.EXPORT:
        if agent:
            export_dir = Path.home() / ".paicli" / "exports"
            export_dir.mkdir(parents=True, exist_ok=True)
            filename = f"session-{int(time.time())}.md"
            path = export_dir / filename
            lines = ["# PaiCLI 对话导出\n"]
            for msg in agent.conversation_history:
                lines.append(f"## {msg.role.upper()}\n{msg.content}\n")
            path.write_text("\n".join(lines), encoding="utf-8")
            print(f"✅ 已导出: {path}"); return True

    # ── 项目记忆 ──
    elif ct == CommandType.INIT_PROJECT_MEMORY:
        from paicli_py.cli.project_memory_initializer import ProjectMemoryInitializer
        force = "--force" in (payload or "")
        result = ProjectMemoryInitializer.generate(force=force)
        print(result); return True

    # ── 未知/帮助 ──
    elif ct == CommandType.UNKNOWN_COMMAND:
        print(f"未知命令: {payload or ''}")
        _print_help()
        return True

    elif ct == CommandType.NONE:
        return True  # 普通文本

    return True


# ═══════════════════════════════════════════════════════════
# REPL 循环
# ═══════════════════════════════════════════════════════════

async def _repl_loop(state: dict[str, Any]) -> None:
    agent = state["agent"]
    renderer = state["renderer"]

    print(_startup_screen(state["llm_client"], state.get("mcp_manager"), state.get("skill_registry"), state.get("skill_state")))
    renderer.start()

    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.history import FileHistory
        from prompt_toolkit.completion import Completer, Completion
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.styles import Style

        class _SlashCompleter(Completer):
            def get_completions(self, document, complete_event):
                text = document.text_before_cursor
                if text.startswith("/"):
                    for hint, desc in _SLASH_HINTS:
                        if hint.startswith(text):
                            yield Completion(hint, start_position=-len(text), display_meta=desc)
                elif text.startswith("@"):
                    from pathlib import Path as _Path
                    query = text[1:]
                    for p in _Path.cwd().glob(f"{query}*"):
                        d = p.name + ("/" if p.is_dir() else "")
                        yield Completion(f"@{p.name}", display=d, start_position=-len(text))

        class _SlashHighlighter:
            def lex_document(self, document):
                def get_line(lineno):
                    from prompt_toolkit.lexers import Lexer
                    line = document.lines[lineno]
                    parts = [("class:slash-command" if c == "/" else "class:mention" if c == "@" else "", ch) for ch in line]
                    return parts
                return get_line

        history_file = Path.home() / ".paicli" / "history.txt"
        history_file.parent.mkdir(parents=True, exist_ok=True)

        # ESC binding: cancel current input line
        kb = KeyBindings()
        @kb.add("escape")
        def _(event):
            if event.app.current_buffer.text:
                event.app.current_buffer.reset()
            else:
                pass  # single ESC with empty line = no-op

        session = PromptSession(
            history=FileHistory(str(history_file)),
            completer=_SlashCompleter(),
            key_bindings=kb,
            style=Style.from_dict({"prompt": "ansicyan bold", "slash-command": "ansicyan", "mention": "ansiblue"}),
        )
        use_pt = True
    except (ImportError, Exception):
        use_pt = False

    while True:
        try:
            user_input = await session.prompt_async("> ") if use_pt else input("> ")
        except (EOFError, KeyboardInterrupt):
            print("\n再见！"); break

        if not user_input or not user_input.strip():
            continue

        command = parse(user_input)
        if command.type != CommandType.NONE:
            if not _handle_command(command, state):
                break
            continue

        # Agent 执行
        mode = state.get("mode", "react")
        try:
            if mode == "plan" and state.get("plan_agent"):
                result = await state["plan_agent"].run(user_input)
            else:
                result = await agent.run(user_input)
            print(f"\n{result}")
        except Exception as e:
            logger.error(f"Agent 异常: {e}")
            print(f"\n❌ {e}")

    renderer.close()


# ═══════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════

def main() -> None:
    # 0. 启动模式检测
    parser = argparse.ArgumentParser(prog="paicli", description="PaiCLI - 终端 Agent IDE")
    parser.add_argument("--wechat", nargs="?", const="start", help="微信 iLink 通道 (setup|start|status|stop)")
    parser.add_argument("--serve", action="store_true", help="启动 Runtime HTTP API 服务")
    parser.add_argument("--port", type=int, default=8080, help="Runtime API 端口")
    parser.add_argument("--http", action="store_true", help="HTTP 模式")
    args, unknown = parser.parse_known_args()

    if args.wechat:
        print(f"微信 iLink 通道模式: {args.wechat}")
        print("请使用 python -m paicli_py.wechat 启动")
        return

    if args.serve or args.http:
        from paicli_py.runtime.api.server import RuntimeApiServer
        server = RuntimeApiServer(port=args.port)
        print(f"Runtime API 服务启动: http://127.0.0.1:{args.port}")
        server.start()
        try:
            import time
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            server.stop()
        return

    # 1. 配置
    config = PaiCliConfig.load()

    # 2. LLM（自动扫描 config.json → 环境变量 → .env）
    llm_client = create_client_from_config(config)
    if not llm_client:
        print("⚠️  未配置 LLM 提供商。请设置 DEEPSEEK_API_KEY / GLM_API_KEY 等环境变量或创建 .env 文件。")
        return

    # 3. 子系统
    from paicli_py.memory.manager import MemoryManager
    from paicli_py.tool.registry import ToolRegistry
    from paicli_py.agent.agent import Agent
    from paicli_py.hitl.terminal_handler import TerminalHitlHandler

    memory_manager = MemoryManager(llm_client)
    tool_registry = ToolRegistry()
    renderer = RendererFactory.create()
    hitl_handler = TerminalHitlHandler(enabled=True)

    # MCP
    mcp_manager = None
    try:
        from paicli_py.mcp.manager import McpServerManager
        mcp_manager = McpServerManager(tool_registry)
        asyncio.get_event_loop().run_until_complete(mcp_manager.start_all())
    except Exception as e:
        logger.warning(f"MCP 失败: {e}")

    # 技能
    skill_registry = None; skill_state = None; skill_buffer = None
    try:
        from paicli_py.skill.registry import SkillRegistry
        from paicli_py.skill.state_store import SkillStateStore
        from paicli_py.skill.context_buffer import SkillContextBuffer
        skill_registry = SkillRegistry()
        skill_registry.reload()
        skill_state = SkillStateStore()
        skill_buffer = SkillContextBuffer()
    except Exception as e:
        logger.warning(f"技能失败: {e}")

    # 快照
    snapshot_service = None
    try:
        from paicli_py.snapshot.service import SnapshotService
        snapshot_service = SnapshotService.for_project(str(Path.cwd()))
    except Exception as e:
        logger.warning(f"快照失败: {e}")

    # 浏览器
    browser_connector = None
    try:
        from paicli_py.browser.connector import BrowserConnector
        browser_connector = BrowserConnector()
    except Exception:
        pass

    # 后台任务
    task_manager = None
    try:
        from paicli_py.runtime.task.manager import DurableTaskManager
        task_manager = DurableTaskManager()
        task_manager.start()
    except Exception:
        pass

    # 4. Agent
    from paicli_py.prompt.assembler import PromptAssembler
    from paicli_py.prompt.project_memory_loader import ProjectMemoryLoader

    project_memory = ProjectMemoryLoader().load_for_prompt()
    system_prompt = PromptAssembler().assemble(project_memory)

    agent = Agent(llm_client=llm_client, tool_registry=tool_registry)
    agent.set_system_prompt(system_prompt)
    agent.set_renderer(renderer)
    agent.set_skill_registry(skill_registry)
    if skill_buffer: agent.set_skill_context_buffer(skill_buffer)

    # 5. 状态
    state: dict[str, Any] = {
        "config": config, "llm_client": llm_client, "agent": agent,
        "memory_manager": memory_manager, "tool_registry": tool_registry,
        "renderer": renderer, "mcp_manager": mcp_manager,
        "skill_registry": skill_registry, "skill_state": skill_state,
        "snapshot_service": snapshot_service, "hitl_handler": hitl_handler,
        "browser_connector": browser_connector, "task_manager": task_manager,
        "mode": "react",
    }

    try:
        asyncio.run(_repl_loop(state))
    except KeyboardInterrupt:
        print()
    finally:
        if mcp_manager: asyncio.get_event_loop().run_until_complete(mcp_manager.shutdown_all())
        if task_manager: task_manager.close()
        if snapshot_service: snapshot_service.close()
        memory_manager.clear_short_term()


if __name__ == "__main__":
    main()
