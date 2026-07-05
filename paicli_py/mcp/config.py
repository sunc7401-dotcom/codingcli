"""MCP 配置加载器。

对应 ``com.paicli.mcp.config`` 包。

从 ``~/.paicli/mcp.json`` 和 ``.paicli/mcp.json`` 加载配置，
支持 ``${VAR}``、``${PROJECT_DIR}``、``${HOME}`` 变量展开。
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any


class McpServerConfig:
    """单个 MCP 服务器的配置。"""

    def __init__(self, name: str, raw: dict[str, Any]) -> None:
        self.name = name
        self.command: list[str] | None = raw.get("command")
        self.args: list[str] = raw.get("args", [])
        self.env: dict[str, str] = raw.get("env", {})
        self.url: str | None = raw.get("url")
        self.headers: dict[str, str] = raw.get("headers", {})
        self.disabled: bool = raw.get("disabled", False)
        self._raw = raw

    @property
    def is_stdio(self) -> bool:
        return self.command is not None

    @property
    def is_http(self) -> bool:
        return self.url is not None


class McpConfigLoader:
    """加载并合并多层 MCP 配置。"""

    GLOBAL_CONFIG = Path.home() / ".paicli" / "mcp.json"
    PROJECT_CONFIG_NAME = ".paicli/mcp.json"

    # 变量展开模式: ${VAR_NAME}
    _VAR_RE = re.compile(r"\$\{([^}]+)\}")

    @classmethod
    def load(cls, project_dir: str | None = None) -> dict[str, McpServerConfig]:
        """加载并合并全局 + 项目级 MCP 配置。

        项目级配置覆盖同名服务器的全局配置。
        """
        merged: dict[str, Any] = {}

        # 1. 全局配置
        if cls.GLOBAL_CONFIG.is_file():
            try:
                global_data = json.loads(cls.GLOBAL_CONFIG.read_text(encoding="utf-8"))
                merged.update(global_data.get("mcpServers", {}))
            except (json.JSONDecodeError, KeyError):
                pass

        # 2. 项目级配置
        if project_dir:
            project_config = Path(project_dir) / cls.PROJECT_CONFIG_NAME
            if project_config.is_file():
                try:
                    project_data = json.loads(project_config.read_text(encoding="utf-8"))
                    merged.update(project_data.get("mcpServers", {}))
                except (json.JSONDecodeError, KeyError):
                    pass

        # 3. 变量展开
        result: dict[str, McpServerConfig] = {}
        context = cls._build_context(project_dir)
        for name, raw in merged.items():
            expanded = cls._expand_vars(raw, context)
            result[name] = McpServerConfig(name, expanded)

        # 4. 自动注册 step_search（如果配置了 STEP_API_KEY）
        if "step_search" not in result:
            step_key = os.environ.get("STEP_API_KEY")
            if step_key:
                result["step_search"] = McpServerConfig("step_search", {
                    "command": "npx",
                    "args": ["-y", "@stepfun/mcp-search"],
                    "env": {"STEP_API_KEY": step_key},
                })

        return result

    @staticmethod
    def _build_context(project_dir: str | None) -> dict[str, str]:
        """构建变量展开上下文。"""
        ctx: dict[str, str] = {}
        # ${HOME}
        ctx["HOME"] = str(Path.home())
        # ${PROJECT_DIR}
        ctx["PROJECT_DIR"] = str(Path(project_dir).resolve()) if project_dir else str(Path.cwd())
        # 环境变量
        ctx.update(os.environ)
        # .env 文件中的变量
        for env_file in [Path(".env"), Path.home() / ".env"]:
            if env_file.is_file():
                try:
                    for line in env_file.read_text(encoding="utf-8").splitlines():
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            key, _, value = line.partition("=")
                            ctx[key.strip()] = value.strip()
                except OSError:
                    pass
        return ctx

    @classmethod
    def _expand_vars(cls, obj: Any, context: dict[str, str]) -> Any:
        """递归展开对象中的 ${VAR} 变量。"""
        if isinstance(obj, str):
            def _replacer(m: re.Match) -> str:
                var_name = m.group(1)
                return context.get(var_name, m.group(0))
            return cls._VAR_RE.sub(_replacer, obj)
        elif isinstance(obj, dict):
            return {k: cls._expand_vars(v, context) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [cls._expand_vars(v, context) for v in obj]
        return obj
