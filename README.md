# LLM-driven refactor-CLI

LLM-driven refactor-CLI 是一个面向 Java Maven 仓库的本地代码检查与安全重构 Agent。项目的核心目标不是让大模型直接改代码，而是把大模型放进一条可审查、可验证、可回滚的软件工程流程中：大模型负责决策和生成候选修改，工具负责提供事实，patcher 负责受控落地，AST 校验和 Maven 测试负责反馈。

## 项目定位

这个项目聚焦 Java 项目的代码检测与重构闭环：

```text
Java Maven 项目
  -> 抽取 AST / Symbol Solver 结构化事实
  -> 静态规则生成候选坏味道
  -> LLM 判断候选是否值得修、风险和优先级
  -> LLM 生成用户可审查的重构计划
  -> 用户确认
  -> LLM 生成 JSON edit operations
  -> RefactorPatcher 受控写入文件
  -> AST Patch Validator 校验结构安全
  -> Maven compile / test / JaCoCo 验证
  -> 失败时回滚并进入 LLM repair loop
  -> 生成报告
```

一句话概括：

```text
LLM 是决策核心
AST / Symbol Solver / 规则 / 测试是证据系统
工具是上下文接口
patcher 是行动接口
验证和回滚是安全系统
```

## 核心能力

- 检测当前目录是否为 Java Maven Git 项目。
- 使用 JavaParser AST 提取类、方法、源码行号、方法调用和字段访问。
- 使用 Symbol Solver 解析方法调用、字段访问、声明类型和 resolved signature。
- 通过静态规则生成代码坏味道候选。
- 由 LLM 对候选 issue 做 triage，判断优先级、风险、是否适合自动修复和重构策略。
- 由 LLM 生成用户可审查的重构计划。
- 提供只读工具，让 LLM 在决策前获取源码片段、相关测试、调用方、计划上下文和验证反馈。
- 用户确认后，由 LLM 生成结构化 JSON edit operations。
- 由 RefactorPatcher 检查 allowed files、路径边界和行号范围后落地修改。
- 使用 AST Patch Validator 拦截语法结构破坏和 public API 意外变化。
- 使用 Maven compile/test 和 JaCoCo 做验证与覆盖感知。
- 验证失败时可回滚并让 LLM 基于失败反馈生成 repair edits。
- 保存任务级 snapshot、patch diff、verification、rollback 和 Markdown report。

## 支持的代码坏味道

当前扫描器会生成以下候选问题：

- Long Method
- Large Class
- Complex Condition
- Unclear Naming
- Dead Code
- Feature Envy
- Duplicate Code

其中：

- Dead Code 优先使用 Symbol Solver 的 resolved signature 判断 private 方法是否被调用。
- Feature Envy 使用方法调用和字段访问的 declaring type 判断外部类型依赖。
- Duplicate Code 优先尝试 PMD CPD，失败时使用本地 normalized-window 规则。
- JavaParser AST 是扫描链路的必要前置条件。

## LLM 决策阶段

### 1. Issue Triage

静态规则和 AST 只提供候选问题，不直接决定最终结果。LLM 会基于结构化 evidence、源码片段、相关测试和调用方判断：

- 候选是否值得修。
- 严重程度和风险等级。
- 是否适合自动修复。
- 应选择哪种重构策略。
- 为什么优先处理该问题。

### 2. Plan

计划阶段先由 deterministic planner 生成安全骨架，再由 LLM 生成最终计划。计划会包含：

- 重构目标。
- 重构类型。
- 允许修改的文件。
- 预期改动。
- 不在本次范围内的内容。
- 风险原因。
- 验证命令。
- 回滚策略。

### 3. Apply

用户确认后，LLM 只能返回结构化 edit operations，例如：

```json
{
  "edits": [
    {
      "file_path": "src/main/java/demo/UserService.java",
      "start_line": 12,
      "end_line": 18,
      "replacement": "..."
    }
  ],
  "explanation": "...",
  "risk_notes": [],
  "verification_focus": []
}
```

LLM 不直接写文件。真正写文件的是 `RefactorPatcher`。

### 4. Repair Loop

如果 apply 后验证失败，系统可以：

```text
回滚到任务快照
  -> 把验证失败反馈交给 LLM
  -> LLM 生成 revised edit operations
  -> 再次 apply
  -> 再次 verify
```

## 只读工具调用

LLM 在做 triage、plan、edit 或 repair 前，可以调用只读工具补充上下文：

- `get_issue_context`
- `read_file`
- `search_code`
- `get_plan_context`
- `get_verification_feedback`

这些工具只提供上下文，不具备写文件能力。

## 安全设计

### 受控 Patch 范围

patcher 会强制检查：

- edit 只能修改 `plan.files_to_modify` 中的文件。
- 路径必须在仓库根目录内。
- 不能修改 `.git`、`target`、`build` 等忽略目录。
- 行号范围必须合法。
- patch 前必须写 snapshot。
- patch 失败必须恢复原文件。

### AST Patch Validator

patch 写入后会重新解析 Java 文件，并检查：

- Java 文件是否仍可被 AST 解析。
- class 声明是否异常变化。
- 非 private 方法签名是否被意外修改。

### Maven 验证

验证阶段会执行：

```text
mvn -q -DskipTests compile
mvn test
mvn org.jacoco:jacoco-maven-plugin:prepare-agent test org.jacoco:jacoco-maven-plugin:report
```

验证结果会保存为结构化 `VerificationResult`，并可作为 repair loop 的输入。

### 任务级回滚

每次 apply 都会保存任务级 snapshot。rollback 只恢复本次任务涉及的文件，不使用 `git reset --hard`，避免误伤用户工作区。

## 项目使用方式

项目只推荐通过命令式交互 shell 使用。

在目标 Java Maven 项目根目录启动：

```bash
refactor-agent chat
```

如果 Windows 找不到 `refactor-agent` 命令，可以在目标 Java 项目目录中使用 Python 项目的虚拟环境入口：

```bat
D:\train\pai-cli\paicli-py\.venv\Scripts\refactor-agent.exe chat
```

进入交互 shell 后，只输入固定命令，不使用自然语言：

```text
refactor-agent> help
refactor-agent> scan
refactor-agent> issues
refactor-agent> select RA-0001
refactor-agent> plan RA-0001
refactor-agent> apply RA-0001 --yes --max-repair-attempts 1
refactor-agent> verify RA-0001
refactor-agent> report
refactor-agent> rollback --yes
refactor-agent> exit
```

常用命令说明：

| 命令 | 作用 |
|---|---|
| `scan` | 扫描当前 Java Maven 项目，并由 LLM 做 issue triage |
| `issues` | 列出最近一次扫描得到的问题 |
| `select RA-0001` | 选择当前操作的 issue |
| `plan RA-0001` | 为指定 issue 生成 LLM 重构计划 |
| `apply RA-0001` | 应用指定 issue 的重构，默认会要求确认 |
| `apply RA-0001 --yes --max-repair-attempts 1` | 跳过低风险确认，并在验证失败时最多 repair 一次 |
| `verify RA-0001` | 执行 Maven 编译、测试和覆盖感知 |
| `characterize RA-0001` | 生成候选行为锁定测试 |
| `report` | 查看最新报告 |
| `rollback --yes` | 回滚最新任务 |
| `status` | 查看当前选中的 issue 和最新任务 |
| `help` | 查看命令帮助 |
| `exit` | 退出交互 shell |

## 源码结构

```text
suncli_py/refactor_agent/
|-- cli.py                 refactor-agent 命令入口
|-- chat.py                命令式交互 shell
|-- commands.py            scan / plan / apply / verify / rollback 编排
|-- project_detector.py    Java Maven Git 项目检测
|-- java_ast.py            JavaParser helper 的 Python 包装
|-- java_ast_helper/       JavaParser + Symbol Solver Maven helper
|-- scanner.py             静态坏味道候选扫描
|-- java_context.py        源码片段、相关测试和调用方上下文收集
|-- prompts.py             LLM 分阶段系统提示词
|-- toolbox.py             暴露给 LLM 的只读工具
|-- llm_assistant.py       LLM triage、plan、edit、repair
|-- planner.py             安全计划骨架生成
|-- patcher.py             受控 patch 应用和 snapshot
|-- patch_validator.py     AST patch 校验
|-- verifier.py            Maven 编译、测试和覆盖验证
|-- coverage.py            JaCoCo 覆盖感知
|-- test_generator.py      Characterization test 生成
|-- rollback.py            任务级回滚
|-- report.py              Markdown 报告生成
|-- storage.py             .paicli/refactor-agent 状态存储
`-- models.py              业务数据模型
```

## 运行产物

运行状态会保存在目标 Java 项目的本地目录：

```text
.paicli/refactor-agent/
|-- issues.json
|-- reports/
|   `-- latest.md
`-- tasks/
    `-- <task_id>/
        |-- issue.json
        |-- plan.json
        |-- plan.md
        |-- snapshot.json
        |-- patch.diff
        |-- diff_summary.txt
        |-- verification.json
        |-- rollback.json
        |-- report.md
        |-- before/
        `-- after/
```

`.paicli/` 属于运行时状态，不应提交到业务仓库。

## 开发与测试

运行 chat 相关测试：

```bash
uv run pytest tests/test_refactor_agent_chat.py -q
```

运行全部测试：

```bash
uv run pytest tests -q
```

编译 JavaParser helper：

```bash
mvn -q -f suncli_py/refactor_agent/java_ast_helper/pom.xml compile
```

## 测评指标

| 指标 | 含义 |
|---|---|
| Triage precision | LLM 保留的问题中有多少是真问题 |
| Triage recall | 标注问题中有多少被扫描和保留 |
| Plan quality | 计划是否明确修改范围、验证和回滚策略 |
| Patch success rate | LLM edit operations 成功应用比例 |
| AST block rate | AST validator 拦截危险修改的能力 |
| Compile/test pass rate | patch 后 Maven 编译和测试通过比例 |
| Repair success rate | 验证失败后 repair loop 修复成功比例 |
| Rollback success rate | 任务级 snapshot 是否能恢复文件 |

## 简历描述

> 设计并实现 LLM-driven Java 代码检查与安全重构 CLI，面向 Maven 仓库结合 JavaParser AST、Symbol Solver、静态坏味道候选、只读代码工具、LLM triage、用户可审查重构计划、JSON edit operations、AST Patch Validator、Maven 编译测试验证、JaCoCo 覆盖感知、repair loop 和任务级回滚，实现可审计、可验证、可恢复的自动化重构闭环。

## License

MIT
