"""浏览器审计元数据 —— 对应 ``com.paicli.browser.BrowserAuditMetadata`` record。"""

from __future__ import annotations

from dataclasses import dataclass

from paicli_py.browser.mode import BrowserMode


@dataclass
class BrowserAuditMetadata:
    browser_mode: str = ""
    sensitive: bool = False
    target_url: str = ""

    @classmethod
    def of(cls, mode: BrowserMode | None, sensitive: bool, target_url: str) -> BrowserAuditMetadata:
        return cls(
            browser_mode=mode.value if mode else "",
            sensitive=sensitive,
            target_url=target_url,
        )
