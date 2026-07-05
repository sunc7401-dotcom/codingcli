"""敏感页面策略 —— 对应 ``com.paicli.browser.SensitivePagePolicy``。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


DEFAULT_PATTERNS = [
    "*.bank.*", "*.alipay.com*", "*.paypal.com*", "*.stripe.com*",
    "github.com/settings/*", "*.feishu.cn/admin*", "*.larkoffice.com/admin*",
    "console.cloud.google.com/*", "*.console.aws.amazon.com/*", "portal.azure.com/*",
]


@dataclass(frozen=True)
class _Rule:
    pattern: str
    regex: re.Pattern


@dataclass
class MatchResult:
    matched: bool
    pattern: str = ""

    @classmethod
    def matched_result(cls, pattern: str) -> MatchResult:
        return cls(matched=True, pattern=pattern)

    @classmethod
    def not_matched(cls) -> MatchResult:
        return cls(matched=False)


class SensitivePagePolicy:
    """敏感 URL 检测策略，支持用户自定义规则文件。"""

    def __init__(self, user_rules_file: str | None = None) -> None:
        self._rules: list[_Rule] = []
        patterns = list(DEFAULT_PATTERNS)

        if user_rules_file:
            p = Path(user_rules_file)
            if p.is_file():
                for line in p.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line and not line.startswith("#"):
                        patterns.append(line)

        for pat in patterns:
            self._rules.append(_Rule(pattern=pat, regex=re.compile(self._glob_to_regex(pat), re.IGNORECASE)))

    @staticmethod
    def _glob_to_regex(glob: str) -> str:
        s = re.escape(glob)
        s = s.replace(r"\*", ".*")
        s = s.replace(r"\?", ".")
        return f"^{s}$"

    def match(self, url: str) -> MatchResult:
        normalized = url.lower()
        for rule in self._rules:
            if rule.regex.search(normalized):
                return MatchResult.matched_result(rule.pattern)
        return MatchResult.not_matched()

    def is_sensitive(self, url: str) -> bool:
        return self.match(url).matched
