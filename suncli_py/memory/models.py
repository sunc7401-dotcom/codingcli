"""Data models and token estimates used by the memory subsystem."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from suncli_py.llm.models import Message


class MemoryType(StrEnum):
    CONVERSATION = "CONVERSATION"
    FACT = "FACT"
    SUMMARY = "SUMMARY"
    TOOL_RESULT = "TOOL_RESULT"


@dataclass(frozen=True)
class MemoryEntry:
    id: str
    content: str
    type: MemoryType
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, str] = field(default_factory=dict)
    token_count: int = 0

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None:
            object.__setattr__(self, "timestamp", self.timestamp.replace(tzinfo=UTC))
        if self.token_count <= 0 and self.content:
            object.__setattr__(self, "token_count", estimate_tokens(self.content))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "content": self.content,
            "type": self.type.value,
            "timestamp": self.timestamp.isoformat().replace("+00:00", "Z"),
            "metadata": dict(self.metadata),
            "tokenCount": self.token_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MemoryEntry:
        timestamp_text = str(data.get("timestamp") or "").replace("Z", "+00:00")
        timestamp = datetime.fromisoformat(timestamp_text) if timestamp_text else datetime.now(UTC)
        raw_metadata = data.get("metadata")
        metadata = (
            {str(key): str(value) for key, value in raw_metadata.items()}
            if isinstance(raw_metadata, dict)
            else {}
        )
        content = str(data.get("content") or "")
        raw_tokens = data.get("tokenCount", data.get("token_count", 0))
        return cls(
            id=str(data["id"]),
            content=content,
            type=MemoryType(str(data["type"])),
            timestamp=timestamp,
            metadata=metadata,
            token_count=int(raw_tokens or estimate_tokens(content)),
        )


def estimate_tokens(text: str | None) -> int:
    if not text:
        return 0
    chinese = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
    return math.ceil(chinese / 1.5 + (len(text) - chinese) / 4.0)


def estimate_message_tokens(messages: list[Message] | None) -> int:
    if not messages:
        return 0
    total = 0
    for message in messages:
        if message.content_parts:
            for part in message.content_parts:
                if part.is_text():
                    total += estimate_tokens(part.text)
                elif part.image_base64:
                    byte_count = len(part.image_base64) * 3 // 4
                    total += max(256, min(4096, byte_count // 768))
                elif part.is_image():
                    total += 1024
        else:
            total += estimate_tokens(message.content)
        for tool_call in message.tool_calls or []:
            total += estimate_tokens(tool_call.arguments)
    return total + len(messages) * 4


@dataclass(frozen=True)
class ContextProfile:
    max_context_window: int
    compression_trigger_ratio: float
    short_term_memory_budget: int
    memory_context_tokens: int

    @property
    def compression_trigger_tokens(self) -> int:
        window = max(8_000, self.max_context_window)
        summary_reserve = min(20_000, max(1_000, window // 4))
        buffer = min(13_000, max(1_000, window // 8))
        return max(1_000, min(window - 1, window - summary_reserve - buffer))

    @classmethod
    def from_window(cls, context_window: int) -> ContextProfile:
        window = max(8_000, context_window)
        trigger = cls._trigger(window)
        return cls(
            max_context_window=window,
            compression_trigger_ratio=max(0.50, min(0.99, trigger / window)),
            short_term_memory_budget=max(4_000, math.floor(window * 0.45)),
            memory_context_tokens=max(500, min(5_000, window // 200)),
        )

    @staticmethod
    def _trigger(window: int) -> int:
        summary_reserve = min(20_000, max(1_000, window // 4))
        buffer = min(13_000, max(1_000, window // 8))
        return max(1_000, min(window - 1, window - summary_reserve - buffer))
