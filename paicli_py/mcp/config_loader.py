"""MCP 配置加载器 —— 对应 ``com.paicli.mcp.config.McpConfigLoader``。"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from paicli_py.mcp.mcp_config_file import McpServerConfig

_VAR_RE = re.compile(r"\$\{([^}]+)\}")


class McpConfigLoader:
    GLOBAL_CONFIG = Path.home() / ".paicli" / "mcp.json"
    PROJECT_CONFIG_NAME = ".paicli/mcp.json"

    @classmethod
    def load(cls, project_dir: str | None = None) -> dict[str, McpServerConfig]:
        merged: dict[str, dict] = {}
        # 全局
        if cls.GLOBAL_CONFIG.is_file():
            try:
                data = json.loads(cls.GLOBAL_CONFIG.read_text(encoding="utf-8"))
                merged.update(data.get("mcpServers", {}))
            except (json.JSONDecodeError, KeyError):
                pass
        # 项目级
        if project_dir:
            pc = Path(project_dir) / cls.PROJECT_CONFIG_NAME
            if pc.is_file():
                try:
                    data = json.loads(pc.read_text(encoding="utf-8"))
                    merged.update(data.get("mcpServers", {}))
                except (json.JSONDecodeError, KeyError):
                    pass
        # 变量展开
        ctx = cls._build_context(project_dir)
        result: dict[str, McpServerConfig] = {}
        for name, raw in merged.items():
            expanded = cls._expand_vars(raw, ctx)
            result[name] = McpServerConfig(name=name, **{k: v for k, v in expanded.items() if k != "name"})
        # 自动注册 step_search
        if "step_search" not in result and os.environ.get("STEP_API_KEY"):
            result["step_search"] = McpServerConfig(
                name="step_search", command="npx",
                args=["-y", "@stepfun/mcp-search"],
                env={"STEP_API_KEY": os.environ["STEP_API_KEY"]},
            )
        return result

    @staticmethod
    def _build_context(project_dir: str | None) -> dict[str, str]:
        ctx = {"HOME": str(Path.home()), "PROJECT_DIR": str(Path(project_dir).resolve()) if project_dir else str(Path.cwd())}
        for env_file in [Path(".env"), Path.home() / ".env"]:
            if env_file.is_file():
                try:
                    for line in env_file.read_text(encoding="utf-8").splitlines():
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, _, v = line.partition("=")
                            ctx[k.strip()] = v.strip()
                except OSError:
                    pass
        ctx.update(os.environ)
        return ctx

    @classmethod
    def _expand_vars(cls, obj, ctx: dict[str, str]):
        if isinstance(obj, str):
            return _VAR_RE.sub(lambda m: ctx.get(m.group(1), m.group(0)), obj)
        elif isinstance(obj, dict):
            return {k: cls._expand_vars(v, ctx) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [cls._expand_vars(v, ctx) for v in obj]
        return obj
