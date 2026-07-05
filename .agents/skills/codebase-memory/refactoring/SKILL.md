---
name: codebase-memory-refactoring
description: Safely rename, extract, split, or move code using codebase-memory-mcp. Use when restructuring existing symbols without breaking dependents.
user-invocable: true
---

# Codebase Memory — Refactoring

## Use When
- The user asks to rename, extract, split, or move a function/class/module.
- You need to restructure code while preserving behavior.

## Workflow
1. Locate the target symbol with `search_graph`.
2. Run `trace_path({function_name: "X", direction: "both"})` to see all callers and callees.
3. Identify all files that reference the symbol (use `search_code` as a cross-check).
4. Plan the refactor in small, testable steps.
5. Apply changes and update all d=1 dependents.
6. Run tests for the touched slice.
7. Use `detect_changes` to verify scope before committing.

## Key Tools
- `search_graph` — locate symbols.
- `trace_path` — full call graph in both directions.
- `search_code` — find textual references.
- `detect_changes` — pre-commit scope check.

## Output Schema
1. Refactor Goal
2. Symbols and Files Affected
3. d=1 Dependents Requiring Updates
4. Test Plan
5. Verification Results
