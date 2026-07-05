# CodingCLI-Py

---

## 快速开始

### 环境要求

- Python >= 3.11
- [uv](https://docs.astral.sh/uv/) 包管理器

### 安装

```bash
git clone https://github.com/sunc7401-dotcom/codingcli.git
cd paicli-py
uv sync
```

### 配置

设置 LLM 提供商 API Key（至少一个）：

```bash
# 智谱 GLM
set GLM_API_KEY=your_key

# DeepSeek
set DEEPSEEK_API_KEY=your_key

# 阶跃星辰
set STEP_API_KEY=your_key

# Kimi / Moonshot
set KIMI_API_KEY=your_key

# 讯飞星火 MaaS
set XFYUN_MAAS_API_KEY=your_key
```

或创建 `.env` 文件：

```ini
GLM_API_KEY=your_key
GLM_MODEL=glm-5.1
```

### 运行

```bash
# 交互式 REPL（默认）
uv run paicli

# Runtime HTTP API 服务
uv run paicli --serve --port 8080

# 查看帮助
uv run paicli --help
```

---

## 功能概览

### Agent 执行模式

| 模式 | 命令 | 说明 |
|------|------|------|
| **ReAct** | 默认 | 推理+行动循环，自动调用工具 |
| **Plan-and-Execute** | `/plan` | 先规划再逐步执行 |
| **Multi-Agent** | `/team` | Planner + Worker + Reviewer 编排 |

### CLI 命令（43 个）

| 分类 | 命令 |
|------|------|
| 基础 | `/exit` `/clear` `/compact` `/cancel` |
| 模型 | `/model [名称]` |
| 模式 | `/plan` `/team` `/hitl on\|off` |
| 记忆 | `/memory` `/memory list\|search\|delete\|clear` `/save` |
| 代码 | `/index` `/search` `/graph` |
| 上下文 | `/context` `/policy` `/config` |
| 审计 | `/audit [N]` |
| 快照 | `/snapshot` `/restore [N]` |
| MCP | `/mcp` `/mcp restart\|logs\|disable\|enable` |
| 浏览器 | `/browser` |
| 任务 | `/task add\|list\|cancel\|log` |
| 技能 | `/skill` `/skill show\|on\|off\|reload` |
| 导出 | `/export` |

### 内置工具

`read_file` `write_file` `list_dir` `glob_files` `grep_code` `execute_command` `web_search` `web_fetch` `search_code` `load_skill` `save_memory` `revert_turn` `create_project` `browser_connect` `browser_disconnect` `browser_status`

---

## 架构

```
paicli_py/
├── agent/        Agent 核心（ReAct / Plan-Execute / Multi-Agent 编排）
├── cli/          命令行入口（解析器 / 补全 / 高亮 / 历史）
├── config/       配置管理（PaiCliConfig + .env）
├── context/      上下文窗口策略（ContextProfile）
├── llm/          LLM 客户端层（7 个提供商 + SSE 流式）
├── memory/       记忆系统（短期 FIFO / 长期 JSON / 压缩 / 检索）
├── tool/         工具注册表（16 个内置工具 + MCP 集成）
├── mcp/          MCP 协议（JSON-RPC 2.0 + stdio/HTTP 双传输）
├── rag/          代码索引（SQLite 向量存储 / 分块 / 嵌入 / 混合检索）
├── plan/         任务规划（拓扑排序 / 批次划分）
├── prompt/       提示词组装（分层模板 / PAI.md 项目记忆）
├── render/       终端渲染器（内联 / 纯文本 / Textual TUI）
├── hitl/         人机协同审批（终端交互 / 审批策略）
├── policy/       安全策略（路径守卫 / 命令守卫 / 审计日志）
├── skill/        技能系统（三层注册 / 上下文缓冲）
├── snapshot/     侧 Git 快照（轮次前后 / 恢复）
├── web/          Web 工具（抓取 / 提取 / 搜索提供商 ×3）
├── browser/      浏览器集成（Chrome CDP / 安全守卫）
├── wechat/       微信 iLink 通道
├── runtime/      运行时 API（HTTP + SSE） + 持久化任务
├── lsp/          LSP 诊断（tree-sitter）
├── tui/          Textual 全屏终端界面
├── image/        图片处理（剪贴板 / 压缩 / 引用）
└── util/         ANSI 样式 / Markdown 渲染 / 分词
```

---



## 开发

```bash
uv sync --group dev    # 安装开发依赖
uv run pytest          # 运行测试
uv run ruff check .    # 代码检查
uv run mypy paicli_py  # 类型检查
```

---

## 许可证

MIT
