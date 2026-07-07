"""内联 Diff 渲染器 —— 使用 ANSI 红绿颜色展示文件变更。

对应 ``com.paicli.render.inline.InlineDiffRenderer``。

使用 LCS（最长公共子序列）算法计算差异，
按 unified diff 格式展示（含上下文行）。
"""

from __future__ import annotations

from enum import Enum
from typing import NamedTuple

# ANSI 颜色
GREEN = "\033[32m"
RED = "\033[31m"
CYAN = "\033[36m"
RESET = "\033[0m"

CONTEXT_LINES = 2


class OpType(Enum):
    EQUAL = "equal"
    ADD = "add"
    DELETE = "delete"


class DiffOp(NamedTuple):
    type: OpType
    text: str
    before_index: int = -1
    after_index: int = -1


class Hunk(NamedTuple):
    before_start: int
    before_count: int
    after_start: int
    after_count: int
    ops: list[DiffOp]

    def header(self) -> str:
        return f"@@ -{self.before_start},{self.before_count} +{self.after_start},{self.after_count} @@"


class InlineDiffRenderer:
    """内联 Diff 渲染器。"""

    @classmethod
    def render(cls, file_path: str, before: str | None, after: str | None) -> None:
        """渲染文件差异。

        Args:
            file_path: 文件路径
            before: 修改前内容（None 表示新建）
            after: 修改后内容（None 表示删除）
        """
        heading = f"\n{CYAN}📝 {file_path}{RESET}"
        print(heading)

        if before is None and after is not None:
            cls._render_new_file(after)
        elif after is None and before is not None:
            cls._render_delete_file(before)
        elif before == after:
            print("  (无变更)")
        elif before is not None and after is not None:
            cls._render_unified_diff(before, after)

    @classmethod
    def _render_new_file(cls, content: str) -> None:
        for line in content.splitlines():
            print(f"{GREEN}+ {line}{RESET}")

    @classmethod
    def _render_delete_file(cls, content: str) -> None:
        for line in content.splitlines():
            print(f"{RED}- {line}{RESET}")

    @classmethod
    def _render_unified_diff(cls, before: str, after: str) -> None:
        before_lines = before.splitlines()
        after_lines = after.splitlines()

        ops = cls._compute_diff(before_lines, after_lines)
        hunks = cls._group_into_hunks(ops, before_lines, after_lines)

        for hunk in hunks:
            print(f"{CYAN}{hunk.header()}{RESET}")
            prev_before_idx = -1
            for op in hunk.ops:
                if op.type == OpType.EQUAL:
                    # 添加省略号表示跳过的上下文
                    if prev_before_idx >= 0 and op.before_index > prev_before_idx + 1:
                        print("  ...")
                    print(f"  {op.text}")
                elif op.type == OpType.ADD:
                    print(f"{GREEN}+ {op.text}{RESET}")
                elif op.type == OpType.DELETE:
                    print(f"{RED}- {op.text}{RESET}")
                prev_before_idx = op.before_index

    # ── LCS Diff 算法 ──────────────────────────────────────

    @staticmethod
    def _compute_diff(a: list[str], b: list[str]) -> list[DiffOp]:
        """使用 LCS DP 算法计算差异。"""
        m, n = len(a), len(b)

        # DP 表: dp[i][j] = LCS 长度
        dp = [[0] * (n + 1) for _ in range(m + 1)]
        for i in range(1, m + 1):
            for j in range(1, n + 1):
                if a[i - 1] == b[j - 1]:
                    dp[i][j] = dp[i - 1][j - 1] + 1
                else:
                    dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])

        # 回溯生成 DiffOp 序列
        ops: list[DiffOp] = []
        i, j = m, n
        while i > 0 or j > 0:
            if i > 0 and j > 0 and a[i - 1] == b[j - 1]:
                ops.append(DiffOp(OpType.EQUAL, a[i - 1], i - 1, j - 1))
                i -= 1
                j -= 1
            elif j > 0 and (i == 0 or dp[i][j - 1] >= dp[i - 1][j]):
                ops.append(DiffOp(OpType.ADD, b[j - 1], i, j - 1))
                j -= 1
            else:
                ops.append(DiffOp(OpType.DELETE, a[i - 1], i - 1, j))
                i -= 1

        ops.reverse()
        return ops

    @staticmethod
    def _group_into_hunks(ops: list[DiffOp], a: list[str], b: list[str]) -> list[Hunk]:
        """将 DiffOp 序列分组为带上下文的 hunks。"""
        # 找出所有非 EQUAL 区域的索引范围
        changed: set[int] = set()
        for idx, op in enumerate(ops):
            if op.type != OpType.EQUAL:
                # 添加前后 CONTEXT_LINES 行
                for offset in range(-CONTEXT_LINES, CONTEXT_LINES + 1):
                    changed.add(idx + offset)

        # 分组连续的 changed 索引
        if not changed:
            return []

        sorted_indices = sorted(changed)
        groups: list[list[int]] = []
        current: list[int] = []
        for idx in sorted_indices:
            if 0 <= idx < len(ops):
                if not current or idx <= current[-1] + (2 * CONTEXT_LINES + 1):
                    current.append(idx)
                else:
                    groups.append(current)
                    current = [idx]
        if current:
            groups.append(current)

        # 构建 Hunks
        hunks: list[Hunk] = []
        for group in groups:
            group_ops = [ops[i] for i in group]
            # 过滤掉超出范围的
            group_ops = [op for op in group_ops if op.before_index >= 0 or op.after_index >= 0]

            before_indices = [op.before_index for op in group_ops if op.before_index >= 0]
            after_indices = [op.after_index for op in group_ops if op.after_index >= 0]

            hunk = Hunk(
                before_start=min(before_indices) + 1 if before_indices else 1,
                before_count=len(before_indices),
                after_start=min(after_indices) + 1 if after_indices else 1,
                after_count=len(after_indices),
                ops=group_ops,
            )
            hunks.append(hunk)

        return hunks
