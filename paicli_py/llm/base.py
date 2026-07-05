"""Abstract OpenAI-compatible LLM client with SSE streaming.

Mirrors ``com.paicli.llm.AbstractOpenAiCompatibleClient``.
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

from paicli_py.llm.client import LlmClient
from paicli_py.llm.models import ChatResponse, ContentPart, Message, StreamListener, ToolCall, _Function


def _read_timeout(key: str, default: int) -> int:
    raw = os.environ.get(key)
    if raw:
        try:
            parsed = int(raw)
            if parsed > 0:
                return parsed
        except ValueError:
            pass
    return default


# Shared httpx client with configurable timeouts (matches Java OkHttp settings)
_shared_client: httpx.AsyncClient | None = None


def _get_shared_client() -> httpx.AsyncClient:
    global _shared_client
    if _shared_client is None:
        _shared_client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=_read_timeout("PAICLI_LLM_CONNECT_TIMEOUT_SECONDS", 60),
                read=_read_timeout("PAICLI_LLM_READ_TIMEOUT_SECONDS", 300),
                write=_read_timeout("PAICLI_LLM_WRITE_TIMEOUT_SECONDS", 60),
                pool=_read_timeout("PAICLI_LLM_CALL_TIMEOUT_SECONDS", 600),
            ),
            limits=httpx.Limits(max_keepalive_connections=10),
        )
    return _shared_client


# ────────────────────────────────────────────────────────────
# Internal accumulators
# ────────────────────────────────────────────────────────────

class _ToolCallAccumulator:
    """Accumulates streaming tool call deltas."""

    def __init__(self) -> None:
        self.id: str = ""
        self.name: str = ""
        self.arguments: str = ""


# ────────────────────────────────────────────────────────────
# Abstract base
# ────────────────────────────────────────────────────────────

class AbstractOpenAiCompatibleClient:
    """Base class for OpenAI-compatible streaming chat clients."""

    # Subclasses MUST override these:
    def _get_api_url(self) -> str: ...
    def _get_model(self) -> str: ...
    def _get_api_key(self) -> str: ...

    # Optional override:
    def _should_send_reasoning_in_history(self) -> bool:
        return False

    def _customize_request(self, headers: dict[str, str]) -> None:
        """Hook to add extra headers before the request is sent."""

    def _customize_body(self, body: dict[str, Any]) -> None:
        """Hook to modify the JSON request body."""

    def _to_image_url(self, part: ContentPart) -> str | None:
        """Convert ContentPart to an image URL string."""
        if part.type == "image_url":
            return part.image_url
        if part.type == "image_base64":
            mime = part.mime_type or "image/png"
            return f"data:{mime};base64,{part.image_base64}"
        return None

    def _http_client(self) -> httpx.AsyncClient:
        return _get_shared_client()

    # ── LlmClient protocol implementation ──────────────────────

    @property
    def model_name(self) -> str:
        return self._get_model()

    @property
    def provider_name(self) -> str:
        return self.__class__.__name__.replace("Client", "").lower()

    @property
    def max_context_window(self) -> int:
        return 128_000

    @property
    def supports_prompt_caching(self) -> bool:
        return False

    @property
    def supports_tools(self) -> bool:
        return True

    @property
    def supports_image_input(self) -> bool:
        return True

    @property
    def prompt_cache_mode(self) -> str:
        return "none"

    # ── Main chat method ──────────────────────────────────────

    async def chat(
        self,
        messages: list[Message],
        tools: list[Any] | None = None,
        listener: StreamListener | None = None,
    ) -> ChatResponse:
        """Send a streaming chat request and return the assembled response."""
        listener = listener or _NO_OP_LISTENER
        body = self._build_request_body(messages, tools)

        headers = {
            "Authorization": f"Bearer {self._get_api_key()}",
            "Content-Type": "application/json",
        }
        self._customize_request(headers)
        self._customize_body(body)

        client = self._http_client()

        response = await client.post(self._get_api_url(), json=body, headers=headers)
        try:
            if response.status_code != 200:
                error_body = response.text
                raise IOError(f"API请求失败: {response.status_code} - {error_body}")

            role = "assistant"
            content_parts: list[str] = []
            reasoning_parts: list[str] = []
            accumulators: list[_ToolCallAccumulator] = []
            input_tokens = 0
            output_tokens = 0
            cached_input_tokens = 0

            async for line in response.aiter_lines():
                trimmed = line.strip()
                if not trimmed or not trimmed.startswith("data:"):
                    continue

                payload = trimmed[len("data:"):].strip()
                if not payload or payload == "[DONE]":
                    break

                try:
                    root = json.loads(payload)
                except json.JSONDecodeError:
                    continue

                # Check for error
                error = root.get("error")
                if error:
                    raise IOError(f"API请求失败: {self._format_streaming_error(error)}")

                # Usage
                usage = root.get("usage")
                if usage:
                    input_tokens = usage.get("prompt_tokens", input_tokens)
                    output_tokens = usage.get("completion_tokens", output_tokens)
                    cached_input_tokens = self._parse_cached_tokens(usage, cached_input_tokens)

                # Choices
                choices: list[dict] = root.get("choices", [])
                if not choices:
                    continue

                choice = choices[0]
                delta: dict = choice.get("delta") or choice.get("message") or {}
                if not delta:
                    continue

                # Role
                delta_role = delta.get("role", "")
                if delta_role:
                    role = delta_role

                # Reasoning delta
                reasoning_delta = self._extract_reasoning_delta(delta)
                if reasoning_delta:
                    reasoning_parts.append(reasoning_delta)
                    listener.on_reasoning_delta(reasoning_delta)

                # Content delta
                content_delta = delta.get("content", "")
                if content_delta:
                    content_parts.append(content_delta)
                    listener.on_content_delta(content_delta)

                # Tool call deltas
                self._merge_tool_call_deltas(accumulators, delta.get("tool_calls", []))

            content = "".join(content_parts)
            reasoning = "".join(reasoning_parts)
            tool_calls = self._build_tool_calls(accumulators)

            if not content and not reasoning and not tool_calls:
                raise IOError("API返回空内容，请检查 provider/model 配置或该模型是否支持当前请求参数")

            return ChatResponse(
                role=role,
                content=content,
                reasoning_content=reasoning if reasoning else None,
                tool_calls=tool_calls,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cached_input_tokens=cached_input_tokens,
            )
        finally:
            # Don't close the shared client here — just the response
            await response.aclose()

    # ── Request body construction ──────────────────────────────

    def _build_request_body(self, messages: list[Message], tools: list[Any] | None) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self._get_model(),
            "stream": True,
            "messages": [],
        }

        for msg in messages:
            msg_node: dict[str, Any] = {"role": msg.role}
            self._append_message_content(msg_node, msg)

            if self._should_send_reasoning_in_history() and msg.role == "assistant" and msg.reasoning_content:
                msg_node["reasoning_content"] = msg.reasoning_content

            if msg.tool_calls:
                tc_list: list[dict] = []
                for tc in msg.tool_calls:
                    tc_list.append({
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    })
                msg_node["tool_calls"] = tc_list

            if msg.tool_call_id:
                msg_node["tool_call_id"] = msg.tool_call_id

            body["messages"].append(msg_node)

        if tools:
            tools_list: list[dict] = []
            for tool in tools:
                # Support both flat format {name, description, parameters}
                # and OpenAI-wrapped format {type: "function", function: {name, description, parameters}}
                if "function" in tool and isinstance(tool["function"], dict):
                    func = tool["function"]
                    tools_list.append({
                        "type": "function",
                        "function": {
                            "name": func.get("name", ""),
                            "description": func.get("description", ""),
                            "parameters": func.get("parameters", {}),
                        },
                    })
                else:
                    tools_list.append({
                        "type": "function",
                        "function": {
                            "name": tool.get("name", ""),
                            "description": tool.get("description", ""),
                            "parameters": tool.get("parameters", {}),
                        },
                    })
            body["tools"] = tools_list

        return body

    def _append_message_content(self, msg_node: dict, msg: Message) -> None:
        if msg.has_image_content() and not self.supports_image_input:
            stripped = msg.without_image_content(
                "当前 provider/model 不支持图片附件，已省略 {count} 张；请基于文字工具结果继续，必要时改用支持视觉输入的模型。"
            )
            msg_node["content"] = stripped.content
            return

        if not msg.has_content_parts():
            msg_node["content"] = msg.content
            return

        content_array: list[dict] = []
        for part in msg.content_parts or []:
            if part is None:
                continue
            if part.is_text() and part.text:
                content_array.append({"type": "text", "text": part.text})
            elif part.is_image():
                image_url = self._to_image_url(part)
                if image_url:
                    content_array.append({"type": "image_url", "image_url": {"url": image_url}})

        if content_array:
            msg_node["content"] = content_array
        else:
            msg_node["content"] = msg.content

    # ── SSE parsing helpers ────────────────────────────────────

    @staticmethod
    def _extract_reasoning_delta(delta: dict) -> str:
        """Extract reasoning content from a delta chunk."""
        rc = delta.get("reasoning_content", "")
        if rc:
            return rc
        reasoning = delta.get("reasoning", "")
        if reasoning:
            return reasoning
        details = delta.get("reasoning_details")
        if isinstance(details, list) and details:
            parts: list[str] = []
            for d in details:
                text = d.get("text") or d.get("content") or ""
                if text:
                    parts.append(text)
            return "".join(parts)
        return ""

    @staticmethod
    def _parse_cached_tokens(usage: dict, fallback: int) -> int:
        """Extract cached/prompt-cache-hit tokens from usage."""
        cached = usage.get("cached_tokens", fallback)
        cached = usage.get("prompt_cache_hit_tokens", cached)
        cached = usage.get("input_cache_hit_tokens", cached)
        prompt_details = usage.get("prompt_tokens_details")
        if isinstance(prompt_details, dict):
            cached = prompt_details.get("cached_tokens", cached)
        input_details = usage.get("input_tokens_details")
        if isinstance(input_details, dict):
            cached = input_details.get("cached_tokens", cached)
        return cached

    @staticmethod
    def _merge_tool_call_deltas(accumulators: list[_ToolCallAccumulator], tc_nodes: list[dict]) -> None:
        for tc in tc_nodes:
            index = tc.get("index", len(accumulators))
            while len(accumulators) <= index:
                accumulators.append(_ToolCallAccumulator())

            acc = accumulators[index]
            tc_id = tc.get("id", "")
            if tc_id:
                acc.id = tc_id

            function: dict = tc.get("function", {})
            name = function.get("name", "")
            if name:
                acc.name += name
            arguments = function.get("arguments", "")
            if arguments:
                acc.arguments += arguments

    @staticmethod
    def _build_tool_calls(accumulators: list[_ToolCallAccumulator]) -> list[ToolCall] | None:
        result: list[ToolCall] = []
        for acc in accumulators:
            if not acc.id:
                continue
            result.append(ToolCall(
                id=acc.id,
                function=_Function(name=acc.name, arguments=acc.arguments),
            ))
        return result or None

    @staticmethod
    def _format_streaming_error(error: dict) -> str:
        message = error.get("message", "")
        code = error.get("code", "")
        if code and message:
            return f"{code} - {message}"
        if message:
            return message
        return json.dumps(error)


# ────────────────────────────────────────────────────────────
# No-op listener
# ────────────────────────────────────────────────────────────

class _NoOpListener:
    def on_reasoning_delta(self, delta: str) -> None:
        pass

    def on_content_delta(self, delta: str) -> None:
        pass


_NO_OP_LISTENER = _NoOpListener()
