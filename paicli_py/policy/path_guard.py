"""路径围栏：所有文件类工具调用必须先经过它。

对应 ``com.paicli.policy.PathGuard``。

定位：HITL 之前的 LLM 输入合法性检查，不是沙箱。

解决三类越界场景：
1. 绝对路径直接逃出项目根（LLM 给出 /etc/passwd）
2. 相对路径用 .. 穿越（../../etc/passwd）
3. 符号链接逃逸（项目内的软链指向外部目录）

设计要点：
- 拒绝时抛 PolicyException
- 不存在的路径也能校验：向上找最近的存在祖先解析 realPath
- 校验通过后返回的 Path 是已规范化的绝对路径
"""

from __future__ import annotations

from pathlib import Path


class PolicyException(Exception):
    """安全策略违规异常。"""
    pass


class PathGuard:
    """文件路径安全校验器。"""

    def __init__(self, root: str) -> None:
        if not root:
            raise ValueError("项目根路径不能为空")

        candidate = Path(root).absolute()
        # macOS /var → /private/var 符号链接：必须把根展开成真实路径
        real = candidate
        try:
            if candidate.exists():
                real = candidate.resolve()
        except OSError:
            pass
        self._root_path = real

    @property
    def root_path(self) -> Path:
        """获取项目根路径（已解析符号链接）。"""
        return self._root_path

    def resolve_safe(self, input_path: str) -> Path:
        """校验路径是否在项目根之内，返回安全的绝对路径。

        Raises:
            PolicyException: 路径越界
        """
        if not input_path:
            raise PolicyException("路径不能为空")

        raw = Path(input_path)
        resolved = raw if raw.is_absolute() else (self._root_path / raw)
        resolved = resolved.normalize()

        # 解析符号链接（包括不存在的路径）
        real_resolved = self._resolve_real_path(resolved)

        # 检查是否在项目根内
        try:
            real_resolved.relative_to(self._root_path)
        except ValueError:
            raise PolicyException(
                f"路径越界: {input_path} 不在项目根 {self._root_path} 之内"
            )

        return real_resolved

    @staticmethod
    def _resolve_real_path(target: Path) -> Path:
        """向上找到最近的存在祖先，调用 resolve() 解析其中的符号链接。

        这样 write_file 给一个尚不存在的目标路径时，
        仍能识别出"路径中段是个软链且指向外部"的越界情况。
        """
        existing = target
        while existing is not None and not existing.exists():
            existing = existing.parent

        if existing is None:
            return target.absolute()

        try:
            real_existing = existing.resolve()
            remainder = existing.relative_to(target) if target.is_relative_to(existing) else Path(".")
            # Compute relative path from existing to target
            remainder = Path(str(target)[len(str(existing)):].lstrip("/\\"))
            result = (real_existing / remainder).resolve()
            return result
        except OSError:
            return target.absolute()
