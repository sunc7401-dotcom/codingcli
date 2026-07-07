"""Agent 核心类 —— 实现 ReAct 循环。

对应 ``com.paicli.agent.Agent``。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from loguru import logger

from suncli_py.agent.agent_budget import AgentBudget, ExitReason
from suncli_py.llm.models import Message, StreamListener
from suncli_py.prompt.assembler import PromptAssembler

if TYPE_CHECKING:
    from suncli_py.llm.client import LlmClient
    from suncli_py.render.protocol import Renderer
    from suncli_py.skill.context_buffer import SkillContextBuffer
    from suncli_py.skill.registry import SkillRegistry
    from suncli_py.tool.registry import ToolRegistry


class Agent:
    """ReAct 循环 Agent。

    核心字段（与 Java 完全一致）：
    - llmClient: LLM 客户端
    - toolRegistry: 工具注册表
    - conversationHistory: 对话历史
    - memoryManager: 记忆管理器
    - historyCompactor: 对话历史压缩器
    - promptAssembler: 提示词组装器
    - renderer: 渲染器
    - skillRegistry / skillContextBuffer: 技能系统
    - externalContextSupplier: 外部上下文提供者
    - hitlEnabledSupplier: HITL 启用状态快照源
    """

    def __init__(self, llm_client: LlmClient, tool_registry: ToolRegistry | None = None) -> None:
        from suncli_py.memory.history_compactor import ConversationHistoryCompactor
        from suncli_py.memory.manager import MemoryManager

        self._llm_client = llm_client
        self._tool_registry = tool_registry if tool_registry is not None else ToolRegistry()
        self._conversation_history: list[Message] = []
        self._memory_manager = MemoryManager(llm_client)
        self._history_compactor = ConversationHistoryCompactor(
            self._memory_manager._compressor if hasattr(self._memory_manager, '_compressor') else None
        )
        self._prompt_assembler = PromptAssembler()

        # 可选依赖（通过 setter 注入）
        self._external_context_supplier: Callable[[], str] = lambda: ""
        self._skill_registry: SkillRegistry | None = None
        self._skill_context_buffer: SkillContextBuffer | None = None
        self._renderer: Renderer | None = None
        self._hitl_enabled_supplier: Callable[[], bool] = lambda: False
        self._return_final_response_when_streamed: bool = False

        # 初始化工具注册表
        self._tool_registry.set_context_profile(self._memory_manager.context_profile)
        self._tool_registry.set_current_model(llm_client.provider_name, llm_client.model_name)
        self._memory_manager.set_project_path(self._tool_registry.project_path)
        self._tool_registry.set_scoped_memory_saver(self._memory_manager.store_fact)

        # 初始化 system prompt
        self._conversation_history.append(Message.system(self._build_system_prompt("")))

    # ── Setter（与 Java 完全一致）─────────────────────────

    def set_llm_client(self, llm_client: LlmClient) -> None:
        self._llm_client = llm_client
        self._memory_manager.set_llm_client(llm_client)
        self._history_compactor.set_llm_client(llm_client)
        self._tool_registry.set_context_profile(self._memory_manager.context_profile)
        self._tool_registry.set_current_model(llm_client.provider_name, llm_client.model_name)

    def set_external_context_supplier(self, supplier: Callable[[], str] | None) -> None:
        self._external_context_supplier = supplier if supplier is not None else (lambda: "")

    def set_skill_registry(self, registry: SkillRegistry) -> None:
        self._skill_registry = registry

    def set_skill_context_buffer(self, buffer: SkillContextBuffer) -> None:
        self._skill_context_buffer = buffer

    def set_renderer(self, renderer: Renderer) -> None:
        self._renderer = renderer

    def set_return_final_response_when_streamed(self, value: bool) -> None:
        self._return_final_response_when_streamed = value

    def set_hitl_enabled_supplier(self, supplier: Callable[[], bool] | None) -> None:
        self._hitl_enabled_supplier = supplier if supplier is not None else (lambda: False)

    # ── 属性 ──────────────────────────────────────────────

    @property
    def conversation_history(self) -> list[Message]:
        return list(self._conversation_history)

    @property
    def budget(self) -> AgentBudget:
        return self._budget

    @property
    def memory_manager(self):
        return self._memory_manager

    @property
    def tool_registry(self):
        return self._tool_registry

    # ── 内部：渲染器懒加载 ─────────────────────────────────

    def _get_renderer(self) -> Renderer:
        if self._renderer is None:
            from suncli_py.render.plain import PlainRenderer
            self._renderer = PlainRenderer()
        return self._renderer

    # ── System Prompt ─────────────────────────────────────

    def _build_system_prompt(self, memory_context: str) -> str:
        parts: list[str] = [self._prompt_assembler.assemble()]
        if memory_context:
            parts.append(memory_context)
        if self._external_context_supplier:
            try:
                extra = self._external_context_supplier()
                if extra:
                    parts.append(extra)
            except Exception:
                pass
        return "\n\n".join(parts)

    def set_system_prompt(self, prompt: str) -> None:
        """Set the system prompt directly, replacing the existing one."""
        if self._conversation_history and self._conversation_history[0].role == "system":
            self._conversation_history[0] = Message.system(prompt)
        else:
            self._conversation_history.insert(0, Message.system(prompt))

    def update_system_prompt_with_memory(self, memory_context: str) -> None:
        new_system = self._build_system_prompt(memory_context)
        if self._conversation_history and self._conversation_history[0].role == "system":
            self._conversation_history[0] = Message.system(new_system)
        else:
            self._conversation_history.insert(0, Message.system(new_system))

    # ── 主循环 run() ──────────────────────────────────────

    async def run(self, user_input: str) -> str:
        logger.info(f"ReAct run started: inputLength={len(user_input) if user_input else 0}")

        self._prune_historical_images()
        self._memory_manager.add_user_message(user_input)
        self._store_explicit_browser_memory_hint(user_input)

        # 检索相关长期记忆
        context_profile = self._memory_manager.context_profile
        memory_context = self._memory_manager.build_context_for_query(user_input, context_profile.memory_context_tokens)
        self.update_system_prompt_with_memory(memory_context)

        # 技能注入
        skill_body = ""
        if self._skill_context_buffer:
            skill_body = self._skill_context_buffer.drain()
        effective_input = f"{skill_body}\n\n{user_input}" if skill_body else user_input

        # 添加用户消息到历史
        self._conversation_history.append(Message.user(effective_input))

        # 创建预算
        self._budget = AgentBudget.from_llm_client(self._llm_client)

        # ReAct 循环
        final_answer = ""
        try:
            while True:
                # 取消检查
                from suncli_py.runtime.cancellation import current_token
                token = current_token()
                if token and token.cancelled:
                    break

                exit_reason = self._budget.check()
                if exit_reason != ExitReason.WITHIN_BUDGET:
                    logger.info(f"Agent 退出: {self._budget.describe_exit(exit_reason)}")
                    final_answer = f"\n\n[{self._budget.describe_exit(exit_reason)}]"
                    break

                self._budget.begin_iteration()

                # 压缩检查
                self._maybe_compact_history()

                # LSP 诊断注入
                self._inject_pending_lsp_diagnostics()

                # 调用 LLM
                messages = list(self._conversation_history)
                tools = self._tool_registry.all_tool_schemas() if self._llm_client.supports_tools else None
                listener = self._create_stream_listener() if self._get_renderer() else None

                start_ns = time.monotonic_ns()
                response = await self._llm_client.chat(messages=messages, tools=tools, listener=listener)
                _elapsed = time.monotonic_ns() - start_ns  # reserved for telemetry

                self._budget.record_tokens(response.input_tokens, response.output_tokens, response.cached_input_tokens)
                self._memory_manager.record_token_usage(response.input_tokens, response.output_tokens, response.cached_input_tokens)

                assistant_msg = Message.assistant(
                    content=response.content,
                    reasoning_content=response.reasoning_content,
                    tool_calls=response.tool_calls,
                )
                self._conversation_history.append(assistant_msg)

                if response.has_tool_calls():
                    self._budget.record_tool_calls(response.tool_calls)

                    tool_results = await self._tool_registry.execute_tools(response.tool_calls)
                    for tc, output in zip(response.tool_calls, tool_results.outputs, strict=False):
                        tool_msg = Message.tool(tc.id, output.content)
                        self._conversation_history.append(tool_msg)
                        self._memory_manager.add_tool_result(tc.name, output.content)

                    self._push_status()
                else:
                    final_answer = response.content
                    self._memory_manager.add_assistant_message(final_answer)
                    break

        except Exception as e:
            logger.error(f"Agent 执行异常: {e}")
            final_answer = f"执行异常: {e}"

        return final_answer

    # ── 辅助方法 ──────────────────────────────────────────

    def clear_history(self) -> None:
        self._conversation_history.clear()
        self._memory_manager.clear_short_term()
        if self._skill_context_buffer:
            self._skill_context_buffer.clear()

    def compact_history_now(self):
        before = len(self._conversation_history)
        self._conversation_history = self._history_compactor.compact(self._conversation_history)
        after = len(self._conversation_history)
        logger.info(f"历史压缩: {before} → {after}")
        return before, after

    def get_context_status(self) -> str:
        return self._memory_manager.get_system_status()

    def current_status(self, phase: str = "") -> dict:
        return {
            "model": f"{self._llm_client.provider_name}/{self._llm_client.model_name}",
            "total_tokens": self._budget.total_input_tokens + self._budget.total_output_tokens,
            "input_tokens": self._budget.total_input_tokens,
            "output_tokens": self._budget.total_output_tokens,
            "hitl_enabled": self._hitl_enabled_supplier(),
            "phase": phase,
        }

    def _prune_historical_images(self) -> None:
        for i, msg in enumerate(self._conversation_history):
            if msg.has_image_content() and msg.role != "user":
                self._conversation_history[i] = msg.without_image_content()

    def _store_explicit_browser_memory_hint(self, text: str) -> None:
        from suncli_py.memory.explicit_memory_hints import extract_fact_from_remember, is_explicit_remember
        if is_explicit_remember(text):
            fact = extract_fact_from_remember(text)
            if fact:
                self._memory_manager.store_fact(fact)

    def _maybe_compact_history(self) -> None:
        if len(self._conversation_history) > 100:
            self._conversation_history = self._history_compactor.compact(self._conversation_history)

    def _inject_pending_lsp_diagnostics(self) -> None:
        try:
            report = self._tool_registry.flush_pending_lsp_diagnostics()
            if report and not report.is_empty and report.prompt_text:
                self._conversation_history.append(Message.system(report.prompt_text))
        except Exception:
            pass

    def _push_status(self) -> None:
        renderer = self._get_renderer()
        try:
            from suncli_py.render.status import StatusInfo
            status = StatusInfo(
                model=f"{self._llm_client.provider_name}/{self._llm_client.model_name}",
                total_tokens=self._budget.total_input_tokens + self._budget.total_output_tokens,
                input_tokens=self._budget.total_input_tokens,
                output_tokens=self._budget.total_output_tokens,
                hitl_enabled=self._hitl_enabled_supplier(),
                phase="react",
            )
            renderer.update_status(status)
        except Exception:
            pass

    def _create_stream_listener(self) -> StreamListener | None:
        renderer = self._get_renderer()

        class _RendererListener:
            def __init__(self, r):
                self._r = r
                self._thinking = False

            def on_reasoning_delta(self, delta: str) -> None:
                if not self._thinking:
                    self._r.begin_thinking("思考中...")
                    self._thinking = True
                self._r.append_thinking(delta)

            def on_content_delta(self, delta: str) -> None:
                if self._thinking:
                    self._r.end_thinking()
                    self._thinking = False
                self._r.append_assistant_content_delta(delta)

        return _RendererListener(renderer)
