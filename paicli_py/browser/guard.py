"""浏览器安全守卫 —— 对应 ``com.paicli.browser.BrowserGuard``。"""

from __future__ import annotations

import json
import re

from paicli_py.browser.check_result import BrowserCheckResult
from paicli_py.browser.mode import BrowserMode
from paicli_py.browser.sensitive_policy import SensitivePagePolicy
from paicli_py.browser.session import BrowserSession

SERVER_PREFIX = "mcp__chrome-devtools__"
WRITE_TOOLS = {"click", "drag", "fill", "fill_form", "handle_dialog", "hover", "press_key", "resize_page", "upload_file", "evaluate_script"}
_PAGE_ID_RE = re.compile(r"page[_-]?id[:\s]*(\S+)", re.IGNORECASE)


class BrowserGuard:
    def __init__(self, session: BrowserSession, policy: SensitivePagePolicy | None = None) -> None:
        self._session = session
        self._policy = policy or SensitivePagePolicy()

    def check(self, tool_name: str, args_json: str, mutate_session: bool = True) -> BrowserCheckResult:
        if not self._is_chrome_tool(tool_name):
            return BrowserCheckResult.allow()
        local_tool = self._local_tool_name(tool_name)
        args = self._parse_args(args_json)
        target_url = self._target_url(local_tool, args) or self._session.last_navigated_url
        if target_url:
            match_result = self._policy.match(target_url)
            if match_result.matched and local_tool in WRITE_TOOLS:
                return BrowserCheckResult.require_approval(
                    notice=f"敏感页面 ({match_result.pattern}): {target_url}",
                    metadata={"browser_mode": self._session.mode.value, "sensitive": True, "target_url": target_url},
                )
        if self._session.mode == BrowserMode.SHARED and local_tool == "close_page":
            page_id = self._page_id(args)
            if page_id and not self._session.is_agent_opened_tab(page_id):
                return BrowserCheckResult.block(reason="共享模式下不能关闭用户自己的标签", metadata={"browser_mode": "shared"})
        if mutate_session and target_url:
            self._session.remember_navigation(target_url)
        return BrowserCheckResult.allow(metadata={"browser_mode": self._session.mode.value, "sensitive": False, "target_url": target_url or ""})

    def apply_after_execution(self, tool_name: str, args_json: str, result: str) -> None:
        if not self._is_chrome_tool(tool_name):
            return
        local_tool = self._local_tool_name(tool_name)
        args = self._parse_args(args_json)
        target_url = self._target_url(local_tool, args)
        if target_url:
            self._session.remember_navigation(target_url)
        if local_tool == "new_page":
            page_id = self._extract_page_id(result)
            if page_id:
                self._session.record_opened_tab(page_id)

    @staticmethod
    def _is_chrome_tool(tool_name: str) -> bool:
        return tool_name.startswith(SERVER_PREFIX)
    @staticmethod
    def _local_tool_name(tool_name: str) -> str:
        return tool_name[len(SERVER_PREFIX):]
    @staticmethod
    def _parse_args(args_json: str) -> dict:
        try: return json.loads(args_json)
        except (json.JSONDecodeError, TypeError): return {}
    @staticmethod
    def _target_url(local_tool: str, args: dict) -> str | None:
        if local_tool in ("navigate_page", "new_page"):
            return args.get("url", "")
        return None
    @staticmethod
    def _page_id(args: dict) -> str | None:
        return args.get("pageIdx") or args.get("pageId") or args.get("uid")
    @staticmethod
    def _extract_page_id(result: str) -> str | None:
        m = _PAGE_ID_RE.search(result)
        return m.group(1) if m else None
