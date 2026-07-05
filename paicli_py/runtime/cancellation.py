"""Cancellation primitives for agent turns and long-running operations.

Mirrors ``com.paicli.runtime.CancellationToken`` and ``CancellationContext``.
"""

from __future__ import annotations

import asyncio
from contextvars import ContextVar
from typing import Any

# Per-task cancellation context (similar to Java's thread-local CancellationContext)
_current_token: ContextVar[CancellationToken | None] = ContextVar("cancellation_token", default=None)


class CancellationToken:
    """A token that can be checked for cancellation and awaited."""

    def __init__(self, label: str = "") -> None:
        self._label = label
        self._cancelled = False
        self._event = asyncio.Event()

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def cancel(self) -> None:
        """Signal cancellation."""
        self._cancelled = True
        self._event.set()

    def check(self) -> None:
        """Raise if cancelled."""
        if self._cancelled:
            raise CancellationError(self._label)

    async def wait(self, timeout: float | None = None) -> bool:
        """Wait until cancelled or timeout. Returns True if cancelled."""
        try:
            await asyncio.wait_for(self._event.wait(), timeout=timeout)
            return True
        except TimeoutError:
            return False

    def __repr__(self) -> str:
        return f"CancellationToken({self._label!r}, cancelled={self._cancelled})"


class CancellationError(Exception):
    """Raised when a cancelled token is checked."""

    def __init__(self, label: str = "") -> None:
        super().__init__(f"Operation cancelled{f': {label}' if label else ''}")


class CancellationScope:
    """Async context manager that sets the current cancellation token."""

    def __init__(self, token: CancellationToken) -> None:
        self._token = token
        self._previous: CancellationToken | None = None

    async def __aenter__(self) -> CancellationToken:
        self._previous = _current_token.get()
        _current_token.set(self._token)
        return self._token

    async def __aexit__(self, *args: Any) -> None:
        _current_token.set(self._previous)


def current_token() -> CancellationToken | None:
    """Return the ambient cancellation token, if any."""
    return _current_token.get()
