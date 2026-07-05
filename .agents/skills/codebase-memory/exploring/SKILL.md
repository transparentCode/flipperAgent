---
name: codebase-memory-exploring
description: Understand architecture and trace execution flows using codebase-memory-mcp. Use when exploring unfamiliar code, answering "how does X work?", or mapping call chains.
user-invocable: true
---

# Codebase Memory — Exploring

## Use When
- The user asks how a module, feature, or function works.
- You need to map an execution flow or data flow.
- You are exploring unfamiliar parts of the codebase.

## Workflow
1. Formulate a concrete question (e.g., "how does signal_app consume ohlcv streams?").
2. Use `search_graph` or `search_code` to locate relevant symbols and files.
3. Use `trace_path` to follow inbound and outbound call chains.
4. Use `get_code_snippet` to read source for key symbols.
5. Summarize the flow in plain language with file paths and symbol names.

## Key Tools
- `search_graph` — find symbols by name/label/file.
- `search_code` — graph-augmented grep.
- `trace_path` — inbound/outbound call chains.
- `get_code_snippet` — read source by qualified name.
- `get_architecture` — high-level codebase overview.

## Output Schema
1. Question or Goal
2. Key Symbols and Files Found
3. Execution/Data Flow Summary
4. Open Questions or Gaps
