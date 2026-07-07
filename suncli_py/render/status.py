"""渲染器状态信息模型 —— 对应 ``com.paicli.render.StatusInfo`` record。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class StatusInfo:
    model: str = ""
    total_tokens: int = 0
    context_window: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    estimated_cost: str = ""
    hitl_enabled: bool = False
    elapsed_millis: int = 0
    phase: str = ""
    mcp_summary: str = ""
    skill_summary: str = ""

    # ── 紧凑构造函数（对齐 Java）─────────────────────────

    @classmethod
    def create(cls, model: str, total_tokens: int, context_window: int, hitl_enabled: bool, elapsed_millis: int) -> StatusInfo:
        """紧凑 5 参数构造函数。"""
        return cls(model=model, total_tokens=total_tokens, context_window=context_window, hitl_enabled=hitl_enabled, elapsed_millis=elapsed_millis)

    # ── 工厂方法（对齐 Java）─────────────────────────────

    @classmethod
    def idle(cls) -> StatusInfo:
        return cls(phase="idle")

    @classmethod
    def active(cls) -> StatusInfo:
        return cls(phase="active")

    @classmethod
    def tokens(cls, model: str, input_tokens: int, output_tokens: int, context_window: int) -> StatusInfo:
        return cls(model=model, input_tokens=input_tokens, output_tokens=output_tokens, context_window=context_window, total_tokens=input_tokens + output_tokens)

    @classmethod
    def with_environment(cls, base: StatusInfo, mcp_summary: str, skill_summary: str) -> StatusInfo:
        return cls(
            model=base.model, total_tokens=base.total_tokens, context_window=base.context_window,
            input_tokens=base.input_tokens, output_tokens=base.output_tokens,
            cached_input_tokens=base.cached_input_tokens, estimated_cost=base.estimated_cost,
            hitl_enabled=base.hitl_enabled, elapsed_millis=base.elapsed_millis, phase=base.phase,
            mcp_summary=mcp_summary, skill_summary=skill_summary,
        )
