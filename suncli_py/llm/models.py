"""Shared LLM data models.

Mirrors the records defined in ``com.paicli.llm.LlmClient``:
  ContentPart, Message, ToolCall, Tool, ChatResponse, StreamListener.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

# ──────────────────────────────────────────────
# ContentPart
# ──────────────────────────────────────────────

@dataclass(frozen=True)
class ContentPart:
    """A multimodal content fragment (text or image)."""

    type: str  # "text" | "image_base64" | "image_url"
    text: str | None = None
    image_base64: str | None = None
    image_url: str | None = None
    mime_type: str | None = None

    @classmethod
    def from_text(cls, text: str) -> ContentPart:
        return cls(type="text", text=text)

    @classmethod
    def from_image_base64(cls, image_base64: str, mime_type: str | None = None) -> ContentPart:
        mime = mime_type or "image/png"
        return cls(type="image_base64", image_base64=image_base64, mime_type=mime)

    @classmethod
    def from_image_url(cls, image_url: str) -> ContentPart:
        return cls(type="image_url", image_url=image_url)

    def is_text(self) -> bool:
        return self.type == "text"

    def is_image(self) -> bool:
        return self.type in ("image_base64", "image_url")


# ──────────────────────────────────────────────
# ToolCall
# ──────────────────────────────────────────────

@dataclass(frozen=True)
class _Function:
    name: str
    arguments: str  # JSON string


@dataclass(frozen=True)
class ToolCall:
    """An LLM-requested tool invocation."""

    id: str
    function: _Function

    @property
    def name(self) -> str:
        return self.function.name

    @property
    def arguments(self) -> str:
        return self.function.arguments

    def parsed_arguments(self) -> dict[str, Any]:
        """Return arguments parsed as a dict."""
        return json.loads(self.function.arguments)


# ──────────────────────────────────────────────
# Tool (schema)
# ──────────────────────────────────────────────

@dataclass(frozen=True)
class Tool:
    """Tool definition sent to the LLM."""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema


# ──────────────────────────────────────────────
# ChatResponse
# ──────────────────────────────────────────────

@dataclass(frozen=True)
class ChatResponse:
    """Full response from one LLM chat call."""

    role: str
    content: str
    reasoning_content: str | None = None
    tool_calls: list[ToolCall] | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0

    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


# ──────────────────────────────────────────────
# Message
# ──────────────────────────────────────────────

@dataclass(frozen=True)
class Message:
    """A single turn in the conversation history."""

    role: str  # system | user | assistant | tool
    content: str
    reasoning_content: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    content_parts: list[ContentPart] | None = None

    # -- factory methods ------------------------------------------------

    @classmethod
    def system(cls, content: str) -> Message:
        return cls(role="system", content=content)

    @classmethod
    def user(cls, content: str) -> Message:
        return cls(role="user", content=content)

    @classmethod
    def user_with_parts(cls, parts: list[ContentPart]) -> Message:
        return cls(role="user", content=Message._plain_text(parts), content_parts=list(parts) if parts else None)

    @classmethod
    def assistant(
        cls,
        content: str,
        reasoning_content: str | None = None,
        tool_calls: list[ToolCall] | None = None,
    ) -> Message:
        return cls(role="assistant", content=content, reasoning_content=reasoning_content, tool_calls=tool_calls)

    @classmethod
    def tool(cls, tool_call_id: str, content: str) -> Message:
        return cls(role="tool", content=content, tool_call_id=tool_call_id)

    # -- helpers --------------------------------------------------------

    def has_content_parts(self) -> bool:
        return bool(self.content_parts)

    def has_image_content(self) -> bool:
        return any(p.is_image() for p in (self.content_parts or []))

    def image_part_count(self) -> int:
        return sum(1 for p in (self.content_parts or []) if p and p.is_image())

    def without_image_content(self, notice_template: str | None = None) -> Message:
        """Return a copy with image parts replaced by a placeholder notice."""
        if not self.has_image_content():
            return self

        template = notice_template or (
            "历史图片附件已省略 {count} 张；"
            "如需重新查看，请使用上文 Image source 或相关工具结果。"
        )
        stripped: list[ContentPart] = []
        omitted = 0
        for p in (self.content_parts or []):
            if p is None:
                continue
            if p.is_image():
                omitted += 1
            else:
                stripped.append(p)

        notice = template.replace("{count}", str(omitted))
        stripped.append(ContentPart.from_text(f"[{notice}]"))
        return Message(
            role=self.role,
            content=self._plain_text(stripped),
            reasoning_content=self.reasoning_content,
            tool_calls=self.tool_calls,
            tool_call_id=self.tool_call_id,
            content_parts=stripped,
        )

    def without_reasoning_content(self) -> Message:
        """Return a copy with reasoning content stripped."""
        if not self.reasoning_content:
            return self
        return Message(
            role=self.role,
            content=self.content,
            reasoning_content=None,
            tool_calls=self.tool_calls,
            tool_call_id=self.tool_call_id,
            content_parts=self.content_parts,
        )

    @staticmethod
    def _plain_text(parts: list[ContentPart] | None) -> str:
        if not parts:
            return ""
        texts: list[str] = []
        image_count = 0
        for p in parts:
            if p is None:
                continue
            if p.is_text() and p.text:
                texts.append(p.text)
            elif p.is_image():
                image_count += 1
        result = "\n\n".join(texts)
        if image_count > 0:
            if result:
                result += "\n\n"
            result += f"[已附加 {image_count} 张图片]"
        return result


# ──────────────────────────────────────────────
# StreamListener (protocol)
# ──────────────────────────────────────────────

@runtime_checkable
class StreamListener(Protocol):
    """Callback interface for streaming LLM responses."""

    def on_reasoning_delta(self, delta: str) -> None: ...
    def on_content_delta(self, delta: str) -> None: ...
