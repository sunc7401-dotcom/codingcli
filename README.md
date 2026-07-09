# Java 代码检查与自动化安全重构 Agent

本项目是一个面向 Java Maven 仓库的本地 Coding Agent，核心业务是对代码进行结构化检查、坏味道识别、重构计划生成、补丁应用、验证、回滚和报告输出。

它不是让大模型直接重写代码，而是把 LLM 放进受控的软件工程流程中：JavaParser AST + Symbol Solver 负责代码结构事实提取、类型解析、调用解析和补丁后校验，LLM 负责解释问题、增强重构计划和生成受控 edit operations，最终由用户确认、AST 校验、Maven 测试、覆盖感知和快照回滚决定变更能否落地。

## 项目定位

项目面向需要维护 Java 项目的开发者或小团队，解决以下问题：

- Java 项目中存在长方法、重复代码、过大类、复杂条件、无用代码、命名不清晰等代码坏味道。
- 直接使用 AI 修改代码风险高，容易改动无关文件或破坏 public API。
- 普通静态分析工具只指出问题，缺少可执行、可验证、可回滚的重构闭环。
- 开发者希望在本地仓库中完成“检查 -> 计划 -> 确认 -> 修改 -> 验证 -> 回滚 -> 报告”的完整流程。

本项目的重点是代码检查与重构业务，而不是通用聊天式代码生成。

## 核心业务流程

```text
Java Maven 仓库
  -> 项目检测
  -> JavaParser AST + Symbol Solver 解析
  -> 坏味道扫描
  -> LLM 问题解释
  -> 生成小步重构计划
  -> 用户确认
  -> 生成受控 patch
  -> AST Patch Validator
  -> Maven 编译与测试
  -> 覆盖感知
  -> 报告输出
  -> 必要时回滚
```

## 主要能力

### 代码检查

系统会扫描当前 Java Maven Git 仓库，识别项目结构、源码目录、测试目录、Maven 环境和 Git 工作区状态。

代码结构识别优先使用真实 Java AST 和 Symbol Solver：

- 类、接口、枚举、record
- 构造器、方法、private 成员
- 方法签名、修饰符、源码起止行
- 方法调用、字段访问、声明类型和 resolved signature
- 方法长度、分支数量、嵌套深度等指标

当 JavaParser 不可用时，系统会降级到文本启发式扫描，并在结果中提示降级风险。

### 坏味道识别

MVP 支持以下代码坏味道：

- Long Method：方法过长或控制流复杂。
- Large Class：类职责过多，字段或方法数量异常。
- Complex Condition：复杂布尔表达式或深层嵌套条件。
- Duplicate Code：重复代码片段。
- Dead Code：未被引用的 private 方法。
- Feature Envy：方法对外部类型的方法调用或字段访问明显多于本类成员。
- Unclear Naming：含义不清晰的变量、方法或类名。

每个 issue 会包含文件路径、代码位置、风险等级、证据指标、影响说明、推荐重构方式和是否适合自动重构。Dead Code 和 Feature Envy 会优先使用 Symbol Solver 的调用解析、字段引用解析和类型解析结果，降低纯文本规则误判。

### LLM Agent 能力

项目中的大模型调用点主要服务于代码理解和重构决策：

- 坏味道解释：基于 AST 指标、代码片段、相关测试和调用上下文，解释为什么这是问题。
- 计划增强：在规则生成的基础计划上补充目标、风险、验证策略和 out_of_scope。
- 受控补丁生成：输出 JSON edit operations，不能直接绕过范围校验写文件。

LLM 不拥有最终写入权。所有模型输出都必须继续经过计划文件范围校验、AST Patch Validator、Maven 验证和回滚保护。

### 小步安全重构

当前自动应用能力聚焦低风险或可控重构：

- Remove Dead Code：删除确认未引用的 private 方法。
- Conservative Extract Method：对简单 Long Method 中连续 accumulator block 进行保守抽取，只新增 private helper，并保持原 public 方法签名不变。
- LLM Controlled Patch：使用结构化 edit operations 应用候选修改。

系统禁止默认执行大范围重写、计划外文件修改、无关格式化和高风险 public API 修改。

### AST Patch Validator

补丁应用后，系统会重新使用 JavaParser 解析计划内 Java 文件，并检查：

- Java 文件是否仍能被真实 AST 解析。
- class / interface / enum / record 声明是否异常变化。
- 非 private 方法和构造器签名是否被意外改变。

如果 LLM 或规则 patch 修改了 public API、破坏语法或改变计划外结构，系统会拒绝本次 patch 并恢复修改前内容。

### 验证与覆盖感知

验证阶段会执行：

- patch 范围检查
- AST patch validation
- Maven 编译或测试命令
- 静态检查提示
- JaCoCo 覆盖报告解析
- 修改区域覆盖感知

系统不会简单把 `mvn test` 通过等同于“重构安全”。如果测试没有覆盖本次修改区域，会在报告中提示风险，并可生成候选 characterization test。

### 快照、回滚与报告

每次应用重构前，系统会创建任务级快照：

- 当前 HEAD
- Git 工作区状态
- 计划文件修改前内容
- patch diff
- 验证结果
- 回滚状态

验证失败或用户不满意时，可以通过 rollback 恢复本次任务前的文件状态。回滚只恢复本次任务涉及的计划文件，不使用 `git reset --hard`，避免误伤用户已有修改。

## 命令使用

### 安装依赖

```bash
uv sync
```

### 扫描代码坏味道

```bash
uv run refactor-agent scan
```

输出项目 profile 和 issue 列表，并保存到：

```text
.paicli/refactor-agent/issues.json
```

### 生成重构计划

```bash
uv run refactor-agent plan --issue RA-0001
```

计划会包含：

- 重构目标
- 修改文件范围
- 预期修改
- 风险原因
- 验证命令
- 回滚策略
- 相关测试和调用上下文

### 应用补丁

```bash
uv run refactor-agent apply --issue RA-0001
```

低风险任务可使用：

```bash
uv run refactor-agent apply --issue RA-0001 --yes
```

应用阶段会创建快照、生成 patch、执行 AST Patch Validator，并输出 diff。

### 验证结果

```bash
uv run refactor-agent verify --issue RA-0001
```

### 生成行为锁定测试

```bash
uv run refactor-agent characterize --issue RA-0001
```

### 回滚

```bash
uv run refactor-agent rollback
```

### 查看报告

```bash
uv run refactor-agent report --latest
```

## 业务模块结构

核心代码集中在 `suncli_py/refactor_agent`：

```text
suncli_py/refactor_agent/
├── cli.py                 命令入口
├── commands.py            scan / plan / apply / verify / rollback / report 编排
├── project_detector.py    Java Maven Git 项目检测
├── scanner.py             坏味道扫描
├── java_ast.py            JavaParser AST Python 包装
├── java_ast_helper/       JavaParser Maven helper
├── java_context.py        目标代码、相关测试和调用上下文收集
├── llm_assistant.py       LLM 解释、计划增强和受控 patch 生成
├── planner.py             小步重构计划生成
├── patcher.py             patch 生成与事务化应用
├── patch_validator.py     AST Patch Validator
├── verifier.py            Maven 验证、静态检查和覆盖感知
├── coverage.py            JaCoCo 覆盖解析
├── test_generator.py      characterization test 生成
├── rollback.py            任务级回滚
├── report.py              重构报告生成
├── storage.py             .paicli/refactor-agent 状态存储
└── models.py              业务数据模型
```

测试代码位于：

```text
tests/test_refactor_agent_*.py
```

## 项目亮点

- 使用 JavaParser + Symbol Solver 做真实 Java AST、类型、方法调用和字段引用解析，不只依赖正则扫描。
- 采用“规则筛选 + LLM 解释/计划增强”的 Agent 工作流。
- LLM 只生成候选解释、计划和 edit operations，不能直接绕过安全边界。
- patch 后重新 AST 解析，防止 public API 被意外修改。
- 支持小步重构、用户确认、Maven 验证、覆盖感知和失败回滚。
- 输出完整证据链报告，便于 code review 和面试展示。

## 开发与验证

```bash
uv sync --group dev
uv run ruff check suncli_py/refactor_agent tests
uv run pytest tests/test_refactor_agent_*.py
mvn -q -f suncli_py/refactor_agent/java_ast_helper/pom.xml compile
```

## 适合写入简历的描述

设计并实现面向 Java Maven 仓库的代码检查与自动化安全重构 Agent，结合 JavaParser AST、Symbol Solver 静态语义分析和 LLM 语义理解，识别 Long Method、Large Class、Duplicate Code、Dead Code、Feature Envy 等代码坏味道，并生成可验证的小步重构计划。系统支持 LLM 结构化计划增强、受控 patch 生成、AST Patch Validator、Maven 测试验证、覆盖感知、任务级快照和失败回滚，降低 AI 自动修改代码引入回归缺陷的风险。

## 许可证

MIT
