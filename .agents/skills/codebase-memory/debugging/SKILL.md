---
name: codebase-memory-debugging
description: Trace bugs and failures using codebase-memory-mcp. Use when the user asks "why is X failing?" or when diagnosing regressions.
user-invocable: true
---

# Codebase Memory — Debugging

## Use When
- The user reports an error or unexpected behavior.
- You need to trace the origin of a failure across call chains.
- You suspect a regression and need to find what changed.

## Workflow
1. Capture the exact error, symptom, or unexpected output.
2. Use `search_code` to find where the error message or related logic lives.
3. Use `trace_path` to follow the call chain backward from the failure point.
4. Use `get_code_snippet` to inspect suspect functions.
5. Use `detect_changes` to see if recent commits touched relevant symbols.
6. Formulate a hypothesis and validate with code/tests.

## Key Tools
- `search_code` — graph-augmented grep for symptoms.
- `trace_path` — inbound/outbound call chains.
- `get_code_snippet` — read source for suspect symbols.
- `detect_changes` — map recent changes to affected symbols.

## Output Schema
1. Symptom or Error
2. Suspect Symbols and Files
3. Call Chain Analysis
4. Recent Changes (if relevant)
5. Hypothesis and Recommended Fix
