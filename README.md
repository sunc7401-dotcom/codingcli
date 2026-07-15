# Refactor Agent

## 当前 `apply` 安全闭环

`apply` 在修改任何业务代码之前先创建不可变快照，并在原始代码上执行 Maven compile、test 和 JaCoCo 基线检查。只有原始项目能够编译、测试通过且覆盖工具可用时才继续。

如果目标修改区域没有可信覆盖，独立的测试生成 Agent 会通过 ReAct 读取目标源码、调用方、现有测试风格和 Maven 配置，只能在确定的 `src/test/java` 候选路径中新建测试。生成的测试必须包含有效 `@Test` 和可观察断言，不能使用禁用测试、空测试或恒真断言；随后必须通过 test-compile、两次完整 test 和 JaCoCo 目标文件覆盖预检。预检通过后才启动修改 Agent。

完整顺序为：

```text
原始快照
  -> 修改前 compile/test/JaCoCo
  -> 覆盖不足时：测试生成 Agent -> 原始代码预检
  -> 修改 Agent
  -> 验证 Agent：diff/compile/test/JaCoCo
  -> 拒绝时仅恢复业务代码，保留已验证测试并反馈修改 Agent
  -> 最终失败或基础设施错误时恢复业务代码并删除自动生成测试
```

测试生成 Agent、修改 Agent 和验证 Agent 使用相同 LLM 配置，但拥有独立角色、工具权限和对话历史。修改 Agent 永远不能编辑自动生成的测试；验证 Agent 每轮从当前代码重新取证。

`refactor-agent` 是面向 Java Maven Git 项目的代码坏味道检查与安全重构 CLI。它结合 JavaParser AST、Symbol Solver、静态规则和 LLM，对候选问题进行语义筛选，生成可审查的重构计划，并通过 AST 校验、Maven 编译测试、覆盖率感知、修复循环和任务级快照控制修改风险。

## 主要能力

- 检测长方法、大类、重复逻辑、特性依恋、过长参数列表、复杂条件和无效代码等坏味道。
- 使用 LLM 阅读受限的源码上下文，对扫描候选进行接受、拒绝或暂缓决策。
- 为指定问题生成结构化重构计划，并由修改 Agent 通过受控工具应用编辑。
- 在写入前校验修改范围、Java 语法结构和公开签名风险。
- `apply` 写入后由独立验证 Agent 自动检查 diff、Maven 编译与测试，并结合 JaCoCo 报告评估覆盖情况。
- 验证失败时把完整证据反馈给修改 Agent 重新生成完整修改；默认最多修复 2 次，最终失败自动回滚初始快照。
- scan、plan、修改和验证统一使用 ReAct 循环，由 LLM 决定何时调用工具以及何时提交结构化结果。
- 提供命令行子命令和交互式 `chat` 工作流。
- 提供项目 `PAI.md`、项目级/全局长期记忆、多轮 Chat 短期记忆和自动上下文压缩。

## 环境要求

- Python 3.11 或更高版本
- Java 与 Maven
- 待检查项目必须是 Maven Git 仓库

安装开发环境：

```bash
uv sync
```

查看命令：

```bash
uv run refactor-agent --help
```

## LLM 配置

默认供应商是 GLM。配置从 `~/.paicli/config.json`、环境变量或当前目录向上的 `.env` 文件读取，也可以通过 `PAICLI_ENV_FILE` 指定 `.env` 文件。

最小 `.env` 示例：

```dotenv
GLM_API_KEY=your-api-key
GLM_MODEL=glm-4-plus
```

当前支持 GLM、DeepSeek、Step、Kimi、Free LLM API、讯飞 MaaS 和 Agnes。各供应商使用对应的大写前缀，例如 `DEEPSEEK_API_KEY`、`KIMI_API_KEY`；可选项包括 `_MODEL`、`_BASE_URL`，讯飞还支持 `_LORA_ID`。

## 使用流程

在目标 Java 项目根目录运行：

```bash
refactor-agent scan
refactor-agent plan --issue RA-0001
refactor-agent apply --issue RA-0001
refactor-agent report --latest
```

其他命令：

```bash
refactor-agent scan --format json
refactor-agent characterize --issue RA-0001
refactor-agent rollback --task TASK_ID
refactor-agent chat
```

### 记忆系统

Python 版长期记忆独立保存在 `~/.paicli-py/memory/long_term_memory.json`，可通过
`PAICLI_PY_MEMORY_DIR` 指定其他目录。项目级记忆只在当前项目可见，`--global` 记忆在所有项目可见：

```bash
refactor-agent save "项目使用 Java 17"
refactor-agent save --global "默认用中文回答"
refactor-agent memory status
refactor-agent memory list
refactor-agent memory search "Java"
refactor-agent memory delete fact-abcd1234
refactor-agent memory clear
```

`refactor-agent init` 会在当前项目生成精简 `PAI.md`，默认不覆盖已有文件；需要重建时使用
`refactor-agent init --force`。启动 LLM 流程时按顺序加载：

1. `~/.paicli-py/PAI.md`
2. 项目根 `PAI.md`
3. `.paicli/PAI.md`
4. `PAI.local.md`
5. `.paicli/PAI.local.md`

PAI.md 可通过单独一行 `@relative/path.md` 导入同一根目录内的文件。总注入内容限制为 24,000 字符。

`chat` 中可使用 `/memory`、`/save`、`/init`、`/compact` 和 `/clear`。其他自然语言输入进入多轮项目助手；
它只能使用只读的文件读取/代码搜索工具。长期记忆只会在用户显式使用保存命令，或明确要求助手“记住”并触发
`save_memory` 时写入，不会从普通对话中自动提取。

`apply`、`characterize` 和冲突回滚默认要求确认；自动化场景可按命令帮助使用 `--yes`。`apply` 必定自动验证，支持 `--max-repair-attempts N`，默认允许 2 次额外修改；设为 `0` 仍会验证，但验证不通过时不再反馈修改。独立 `verify` 命令已取消，chat 中输入 `verify` 会提示改用 `apply`。

ReAct 循环默认不设置 token 硬限制，连续 3 轮重复同一工具调用会判定停滞，最多执行 50 轮。可通过 `PAICLI_REACT_TOKEN_BUDGET`、`PAICLI_REACT_STAGNATION_WINDOW` 和 `PAICLI_REACT_HARD_MAX_ITERATIONS` 调整。

运行状态写入目标项目的 `.paicli/refactor-agent/`，包括扫描结果、计划、不可变初始快照、验证结果和报告。每次修改/验证的产物保存在任务目录的 `attempts/NN/`，Agent 消息写入审计记录；任务根目录的 `patch.diff`、`verification.json` 和 `report.md` 始终指向最新结果。该目录属于运行时数据，不应提交到业务仓库。

## 代码结构

```text
suncli_py/
|-- config/                         LLM 配置与 .env 解析
|-- llm/                            LLM 协议、工厂和供应商客户端
`-- refactor_agent/
    |-- core/                       领域模型与状态存储
    |-- analysis/                   项目识别、Java AST、扫描、上下文和覆盖率
    |   |-- java_ast_helper/        JavaParser 与 Symbol Solver 辅助程序
    |   `-- smell_rules/            坏味道规则包
    |-- assistant/                  LLM 判断、提示词、只读工具和计划生成
    |-- execution/                  补丁、校验、测试生成、验证和回滚
    `-- interface/                  CLI、聊天、命令编排和报告
tests/                              Refactor Agent 与配置测试
```

## 开发与验证

```bash
uv run pytest tests -q
uv run ruff check suncli_py tests
uv run mypy suncli_py
mvn -q -f suncli_py/refactor_agent/analysis/java_ast_helper/pom.xml compile
```

## License

MIT
