# LLM-driven refactor-CLI

LLM-driven refactor-CLI is a local Java code inspection and safe refactoring agent for Maven repositories. It uses JavaParser AST, Symbol Solver, static code-smell candidates, LLM decision making, controlled edit operations, AST validation, Maven verification, repair loops, task snapshots, and rollback to make automated refactoring reviewable and recoverable.

The project is centered on one workflow:

```text
Java Maven repository
  -> extract deterministic code facts
  -> let the LLM triage issues and choose a strategy
  -> generate a user-reviewable refactoring plan
  -> confirm before changing code
  -> let the LLM generate structured edit operations
  -> apply edits through a controlled patcher
  -> validate AST shape and public API safety
  -> run compile/tests/coverage
  -> repair or roll back when verification fails
```

## Core Idea

The LLM is the decision core, but it does not directly write files.

```text
LLM makes decisions.
AST, Symbol Solver, rules, tests, and tools provide evidence.
RefactorPatcher applies controlled edits.
AST validation and Maven tests provide feedback.
Snapshots make every task recoverable.
```

This design keeps the model useful for semantic judgment and code generation while keeping file writes, validation, and rollback under deterministic control.

## Main Capabilities

- Project detection for Java Maven Git repositories.
- JavaParser AST extraction for classes, methods, source ranges, method calls, and field accesses.
- Symbol Solver resolution for declaring types and resolved method signatures.
- Static candidate generation for common Java code smells.
- LLM-driven issue triage, priority, risk, and refactoring strategy.
- LLM-generated refactoring plans that users can review before applying.
- Read-only LLM tools for source context, related tests, callers, plan context, and verification feedback.
- JSON edit operations instead of direct model file writes.
- Controlled patch application with allowed-file and path-boundary checks.
- AST patch validation to catch unsafe structural changes.
- Maven compile/test and JaCoCo coverage feedback.
- Optional LLM repair loop after verification failure.
- Task-level snapshot, rollback, and Markdown reports.

## Architecture

```text
refactor-agent scan
  -> ProjectDetector.detect
  -> JavaSmellScanner.scan
  -> JavaParserAnalyzer.analyze_files
  -> JavaAstDump.java
  -> RefactorLlmAssistant.triage_issues
  -> RefactorAgentStorage.save_scan_result

refactor-agent plan --issue RA-0001
  -> RefactorAgentStorage.find_issue
  -> RefactorPlanner.create_plan
  -> RefactorLlmAssistant.generate_plan
  -> RefactorAgentStorage.save_plan

refactor-agent apply --issue RA-0001
  -> RefactorAgentStorage.load_latest_plan_for_issue
  -> user confirmation
  -> RefactorLlmAssistant.generate_edit_plan
  -> RefactorPatcher.generate_changes
  -> RefactorPatcher.apply_changes
  -> AstPatchValidator.validate
  -> optional VerificationPipeline.verify
  -> optional RefactorLlmAssistant.generate_repair_edit_plan

refactor-agent verify
  -> VerificationPipeline.verify
  -> CoverageAnalyzer.assess
  -> ReportGenerator.generate

refactor-agent rollback
  -> TaskRollbacker.rollback
  -> ReportGenerator.generate
```

## LLM-Driven Stages

### 1. Issue Triage

The scanner generates candidates from AST and static rules. The LLM decides which candidates are worth fixing, how risky they are, whether they are suitable for automation, and which refactoring strategy should be used.

The scanner is evidence, not the final judge.

### 2. Refactoring Plan

The planner creates a safe scaffold. The LLM turns it into a user-reviewable plan with:

- goal
- refactoring type
- files to modify
- expected changes
- out-of-scope items
- risk reasons
- verification commands
- rollback strategy

### 3. Controlled Edit Generation

After user confirmation, the LLM returns structured JSON edit operations:

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

The model does not claim files were changed. `RefactorPatcher` decides whether the edits can be applied.

### 4. Repair Loop

When verification fails, the system can roll back the failed patch, send verification feedback to the LLM, ask for revised edit operations, apply them, and verify again.

## Read-Only LLM Tools

The LLM can request more context before deciding:

- `get_issue_context`
- `read_file`
- `search_code`
- `get_plan_context`
- `get_verification_feedback`

These tools are implemented in `suncli_py/refactor_agent/toolbox.py`. They provide code and verification context without giving the LLM write access.

## Supported Code Smells

The scanner currently generates candidates for:

- Long Method
- Large Class
- Complex Condition
- Unclear Naming
- Dead Code
- Feature Envy
- Duplicate Code

Implementation notes:

- Dead Code uses Symbol Solver resolved signatures when available.
- Feature Envy uses resolved declaring types for method calls and field accesses.
- Duplicate Code tries PMD CPD first and falls back to a local normalized-window detector.
- JavaParser AST is required for scanning.

## Safety Controls

### Controlled Patch Scope

The patcher enforces:

- edits must target `plan.files_to_modify`
- paths must stay inside the repository
- ignored build/runtime directories cannot be modified
- line ranges must be valid
- patch diffs and snapshots must be written
- files are restored if patch application fails

### AST Patch Validation

After patching, changed Java files are parsed again. The validator checks:

- Java files remain parseable
- class declarations are not unexpectedly changed
- externally visible method signatures are preserved unless explicitly allowed

### Maven Verification

Verification runs:

```text
mvn -q -DskipTests compile
mvn test
mvn org.jacoco:jacoco-maven-plugin:prepare-agent test org.jacoco:jacoco-maven-plugin:report
```

The result is stored as a structured verification artifact and can be used by the repair loop.

### Task-Level Rollback

Every applied task stores a local snapshot. Rollback restores only files touched by that task and does not use `git reset --hard`.

## Command Usage

Install dependencies:

```bash
uv sync
```

Scan Java code-smell candidates and let the LLM triage them:

```bash
uv run refactor-agent scan
```

Generate a user-reviewable refactoring plan:

```bash
uv run refactor-agent plan --issue RA-0001
```

Apply a confirmed refactoring:

```bash
uv run refactor-agent apply --issue RA-0001
```

Apply with one repair attempt after verification failure:

```bash
uv run refactor-agent apply --issue RA-0001 --yes --max-repair-attempts 1
```

Run verification:

```bash
uv run refactor-agent verify --issue RA-0001
```

Generate a characterization test before refactoring:

```bash
uv run refactor-agent characterize --issue RA-0001
```

Rollback the latest task:

```bash
uv run refactor-agent rollback
```

Show the latest report:

```bash
uv run refactor-agent report --latest
```

## Source Map

```text
suncli_py/refactor_agent/
|-- cli.py                 command-line parser
|-- commands.py            scan / plan / apply / verify / rollback orchestration
|-- project_detector.py    Java Maven Git project detection
|-- java_ast.py            Python wrapper around JavaParser helper
|-- java_ast_helper/       JavaParser + Symbol Solver Maven helper
|-- scanner.py             static smell candidate scanner
|-- java_context.py        source excerpts, tests, and caller context
|-- prompts.py             LLM system prompts for each stage
|-- toolbox.py             read-only tools exposed to the LLM
|-- llm_assistant.py       LLM triage, planning, edit generation, repair loop
|-- planner.py             safe plan scaffold generation
|-- patcher.py             controlled patch application and snapshots
|-- patch_validator.py     AST-level patch validation
|-- verifier.py            Maven compile/test/coverage verification
|-- coverage.py            JaCoCo coverage assessment
|-- test_generator.py      characterization test generation
|-- rollback.py            task-level rollback
|-- report.py              Markdown report generation
|-- storage.py             repository-local task state
`-- models.py              structured domain models
```

## Stored Artifacts

Runtime state is stored in the target repository:

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

`.paicli/` is ignored because it is runtime state.

## Development And Testing

Run focused tests:

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

## Evaluation Metrics

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

> Built an LLM-driven Java code inspection and safe refactoring CLI for Maven repositories. The system combines JavaParser AST, Symbol Solver, static smell candidates, read-only code tools, structured LLM triage, user-reviewable refactoring plans, JSON edit operations, AST patch validation, Maven compile/test verification, JaCoCo coverage awareness, repair loops, and task-level rollback to make automated refactoring auditable and recoverable.

## License

MIT
