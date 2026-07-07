"""计划审核输入解析器 —— 对应 ``com.paicli.cli.PlanReviewInputParser``。

解析用户在计划审核阶段的输入，映射为 EXECUTE / SUPPLEMENT / CANCEL 决策。
"""

from __future__ import annotations

from enum import Enum, auto


class ReviewDecision(Enum):
    EXECUTE = auto()     # 执行计划
    SUPPLEMENT = auto()  # 补充修改
    CANCEL = auto()      # 取消


def parse_review_input(user_input: str) -> ReviewDecision:
    """解析审核输入。

    - y / yes / 执行 / enter(空) → EXECUTE
    - s / supplement / 补充 → SUPPLEMENT
    - n / no / cancel / 取消 → CANCEL
    """
    t = user_input.strip().lower()

    # 执行
    if t in ("y", "yes", "ok", "go", "执行", ""):
        return ReviewDecision.EXECUTE

    # 补充
    if t in ("s", "supplement", "补充", "修改"):
        return ReviewDecision.SUPPLEMENT
    if t.startswith("s ") or t.startswith("补充 "):
        return ReviewDecision.SUPPLEMENT

    # 取消
    if t in ("n", "no", "cancel", "取消", "算了"):
        return ReviewDecision.CANCEL

    # 其他都视为补充
    return ReviewDecision.SUPPLEMENT
