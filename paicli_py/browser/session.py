"""浏览器会话管理 —— 对应 ``com.paicli.browser.BrowserSession``。"""

from __future__ import annotations

from paicli_py.browser.mode import BrowserMode


class BrowserSession:
    """浏览器会话状态（全同步方法，线程安全）。"""

    def __init__(self) -> None:
        self._mode = BrowserMode.ISOLATED
        self._browser_url = "http://127.0.0.1:9222"
        self._last_navigated_url: str | None = None
        self._agent_opened_tabs: set[str] = set()

    @property
    def mode(self) -> BrowserMode:
        return self._mode

    @property
    def browser_url(self) -> str:
        return self._browser_url

    @property
    def last_navigated_url(self) -> str | None:
        return self._last_navigated_url

    def switch_to_isolated(self) -> None:
        self._mode = BrowserMode.ISOLATED
        self._last_navigated_url = None
        self._agent_opened_tabs.clear()

    def switch_to_shared(self, browser_url: str) -> None:
        self._mode = BrowserMode.SHARED
        self._browser_url = browser_url
        self._last_navigated_url = None
        self._agent_opened_tabs.clear()

    def remember_navigation(self, url: str) -> None:
        self._last_navigated_url = url

    def record_opened_tab(self, page_id: str) -> None:
        self._agent_opened_tabs.add(page_id)

    def is_agent_opened_tab(self, page_id: str) -> bool:
        return page_id in self._agent_opened_tabs

    @property
    def agent_opened_tabs(self) -> set[str]:
        return self._agent_opened_tabs.copy()

    def clear_agent_opened_tabs(self) -> None:
        self._agent_opened_tabs.clear()
