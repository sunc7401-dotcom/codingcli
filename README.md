# PaiCLI Python

PaiCLI Python is a terminal-based AI coding assistant framework with a focused Java refactoring agent. The main highlight of this repository is the `refactor-agent` workflow: an LLM-driven Java code inspection and safe refactoring agent for local Maven projects.

The refactoring workflow is designed around a simple principle:

```text
LLM makes decisions.
Tools provide evidence.
Patchers apply controlled edits.
Validators and tests provide feedback.
Snapshots make the workflow recoverable.
```

## What This Project Does

This repository contains two related layers.

### PaiCLI Agent Runtime

The general PaiCLI runtime provides:

- terminal chat loop
- LLM provider abstraction
- tool calling
- memory management
- project prompt loading
- code search and RAG utilities
- MCP integration
- browser and web tools
- snapshot and rollback support
- terminal rendering and HITL approval infrastructure

Key source directories:

```text
suncli_py/agent/      ReAct-style agent loop
suncli_py/tool/       tool registry and built-in tools
suncli_py/memory/     short-term and long-term memory
suncli_py/llm/        LLM client and provider adapters
suncli_py/rag/        code indexing and retrieval utilities
suncli_py/mcp/        MCP client and server integration
suncli_py/snapshot/   task snapshot support
suncli_py/cli/        main paicli command-line entry
```

### Java Safe Refactor Agent

The `suncli_py/refactor_agent` package implements a Java code inspection and refactoring workflow:

- detect whether the current repository is a Java Maven Git project
- extract Java structure with JavaParser AST
- resolve methods, fields, and declaring types with Symbol Solver
- generate static rule candidates for code smells
- let the LLM triage candidates and decide priority, risk, and strategy
- let the LLM generate a user-reviewable refactoring plan
- require user confirmation before applying changes
- let the LLM generate structured edit operations
- apply edits through a deterministic patcher
- validate changed Java files with AST checks
- run Maven compile, tests, and JaCoCo coverage analysis
- feed verification failures back into the LLM repair loop
- keep task snapshots and rollback support
- generate Markdown reports for review

## Refactor Agent Architecture

```text
Java Maven repository
  -> ProjectDetector
  -> JavaParserAnalyzer
  -> JavaAstDump.java
  -> JavaSmellScanner
  -> RefactorLlmAssistant.triage_issues
  -> RefactorPlanner.create_plan
  -> RefactorLlmAssistant.generate_plan
  -> user confirmation
  -> RefactorLlmAssistant.generate_edit_plan
  -> RefactorPatcher
  -> AstPatchValidator
  -> VerificationPipeline
  -> optional LLM repair loop
  -> ReportGenerator / TaskRollbacker
```

The static scanner and AST layer do not make the final decision. They provide structured evidence to the LLM. The LLM decides which candidates are real, how risky they are, whether they are suitable for automation, and what refactoring strategy should be used.

## LLM-Driven Workflow

The refactor agent requires an LLM for the main workflow:

- `scan` requires LLM triage.
- `plan` requires LLM plan generation.
- `apply` requires LLM edit operations.
- verification failure can trigger LLM repair edits.

The LLM is not given direct file write access. It returns JSON decisions or edit operations such as:

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

`RefactorPatcher` is responsible for turning these operations into file changes. It checks allowed files, path boundaries, line ranges, snapshots, diffs, and AST validation before accepting the patch.

## Tool Calling

The LLM can call read-only tools before deciding:

- `get_issue_context`
- `read_file`
- `search_code`
- `get_plan_context`
- `get_verification_feedback`

These tools are implemented in `suncli_py/refactor_agent/toolbox.py`. They let the LLM inspect source excerpts, related tests, direct callers, current plans, and verification errors without giving it write access.

## Supported Java Code Smells

The scanner currently generates candidates for:

- Long Method
- Large Class
- Complex Condition
- Unclear Naming
- Dead Code
- Feature Envy
- Duplicate Code

Important implementation points:

- Dead Code uses Symbol Solver resolved signatures when available.
- Feature Envy uses resolved declaring types for method calls and field accesses.
- Duplicate Code tries PMD CPD first and falls back to a local normalized-window detector.
- JavaParser AST is required for the scanner path.

## Safety Controls

The project uses several safety layers:

### 1. Structured Facts Before LLM Decisions

JavaParser and Symbol Solver extract source ranges, methods, classes, method calls, field accesses, declaring types, and resolved signatures. The LLM receives these facts as evidence instead of guessing from raw repository text.

### 2. User-Reviewable Plans

Before code is modified, the system saves a plan containing:

- goal
- refactoring type
- files to modify
- expected changes
- out-of-scope items
- risk reasons
- verification commands
- rollback strategy

### 3. Controlled Patch Application

The LLM only returns edit operations. The patcher enforces:

- edits must target `plan.files_to_modify`
- paths must stay inside the repository
- ignored directories cannot be modified
- line ranges must be valid
- diffs and snapshots must be written
- files are restored if application fails

### 4. AST Patch Validation

After patching, Java files are parsed again. The validator checks:

- changed Java files remain parseable
- class declarations are not unexpectedly changed
- externally visible method signatures are preserved unless explicitly allowed

### 5. Verification Feedback

Verification runs:

```text
mvn -q -DskipTests compile
mvn test
mvn org.jacoco:jacoco-maven-plugin:prepare-agent test org.jacoco:jacoco-maven-plugin:report
```

The result is stored as a structured `VerificationResult` and can be sent back to the LLM for repair.

### 6. Task-Level Rollback

The system stores task-local snapshots under `.paicli/refactor-agent/tasks/<task_id>/`. Rollback restores only files touched by the task and does not use `git reset --hard`.

## Command Usage

Install dependencies:

```bash
uv sync
```

Run the main PaiCLI assistant:

```bash
uv run paicli
```

Run the Java refactor agent:

```bash
uv run refactor-agent scan
uv run refactor-agent plan --issue RA-0001
uv run refactor-agent apply --issue RA-0001
uv run refactor-agent verify --issue RA-0001
uv run refactor-agent report --latest
```

Apply with automatic repair attempts:

```bash
uv run refactor-agent apply --issue RA-0001 --yes --max-repair-attempts 1
```

Generate a characterization test before refactoring:

```bash
uv run refactor-agent characterize --issue RA-0001
```

Rollback the latest task:

```bash
uv run refactor-agent rollback
```

## Refactor Agent Source Map

```text
suncli_py/refactor_agent/
├── cli.py                 command-line parser
├── commands.py            scan / plan / apply / verify / rollback orchestration
├── project_detector.py    Java Maven Git project detection
├── java_ast.py            Python wrapper around JavaParser helper
├── java_ast_helper/       JavaParser + Symbol Solver Maven helper
├── scanner.py             static smell candidate scanner
├── java_context.py        source excerpts, tests, and caller context
├── prompts.py             LLM system prompts for each stage
├── toolbox.py             read-only tools exposed to the LLM
├── llm_assistant.py       LLM triage, planning, edit generation, repair loop
├── planner.py             safe plan scaffold generation
├── patcher.py             controlled patch application and snapshots
├── patch_validator.py     AST-level patch validation
├── verifier.py            Maven compile/test/coverage verification
├── coverage.py            JaCoCo coverage assessment
├── test_generator.py      characterization test generation
├── rollback.py            task-level rollback
├── report.py              Markdown report generation
├── storage.py             repository-local task state
└── models.py              structured domain models
```

## Stored Artifacts

Refactor agent state is stored locally in the target repository:

```text
.paicli/refactor-agent/
├── issues.json
├── reports/
│   └── latest.md
└── tasks/
    └── <task_id>/
        ├── issue.json
        ├── plan.json
        ├── plan.md
        ├── snapshot.json
        ├── patch.diff
        ├── diff_summary.txt
        ├── verification.json
        ├── rollback.json
        ├── report.md
        ├── before/
        └── after/
```

`.paicli/` is ignored because it is runtime state.

## Development And Testing

Run the focused tests:

```bash
uv run pytest tests/test_refactor_agent_*.py
```

Run all tests:

```bash
uv run pytest tests -q
```

Compile the JavaParser helper:

```bash
mvn -q -f suncli_py/refactor_agent/java_ast_helper/pom.xml compile
```

Useful local checks:

```bash
uv run ruff check suncli_py/refactor_agent tests
uv run python -m compileall -q suncli_py/refactor_agent tests
```

## Evaluation Ideas

Recommended metrics for evaluating the refactor agent:

| Metric | Meaning |
|---|---|
| Triage precision | How many LLM-kept issues are real code smells |
| Triage recall | How many labeled issues are found and kept |
| Plan quality | Whether plans define safe scope, verification, and rollback |
| Patch success rate | How often LLM edit operations apply cleanly |
| AST block rate | How often dangerous structural edits are blocked |
| Compile/test pass rate | How often patches pass Maven verification |
| Repair success rate | How often failed patches are fixed by the repair loop |
| Rollback success rate | Whether task snapshots restore touched files |

## Resume Summary

Suggested project description:

> Built an LLM-driven Java code inspection and safe refactoring agent for Maven repositories. The system combines JavaParser AST, Symbol Solver, static smell candidates, read-only code tools, structured LLM triage, user-reviewable refactoring plans, JSON edit operations, AST patch validation, Maven compile/test verification, JaCoCo coverage awareness, repair loops, and task-level rollback to make automated refactoring auditable and recoverable.

## License

MIT
