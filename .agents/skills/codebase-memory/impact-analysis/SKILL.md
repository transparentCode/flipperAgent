---
name: codebase-memory-impact-analysis
description: Assess blast radius before editing code using codebase-memory-mcp. Use when the user asks "what will break if I change X?" or before modifying shared symbols.
user-invocable: true
---

# Codebase Memory — Impact Analysis

## Use When
- The user asks what depends on a symbol or module.
- You are about to edit an existing function, class, or method.
- You need to classify risk before proceeding with a change.

## Workflow
1. Identify the target symbol(s) using `search_graph`.
2. Run `trace_path({function_name: "X", direction: "upstream"})` to find direct and indirect callers.
3. Run `trace_path({function_name: "X", direction: "downstream"})` to find callees and dependencies.
4. Map results to execution flows and critical paths.
5. Classify risk:
   - **HIGH/CRITICAL**: d=1 direct callers/importers will break.
   - **MEDIUM**: d=2 indirect dependents likely affected.
   - **LOW**: d=3 transitive deps may need testing.

## Key Tools
- `search_graph` — locate the symbol.
- `trace_path` — blast radius / call chain.
- `detect_changes` — map git diff to affected symbols.

## Output Schema
1. Target Symbol
2. Direct Dependents (d=1)
3. Indirect Dependents (d=2)
4. Affected Execution Flows
5. Risk Classification and Recommended Action
