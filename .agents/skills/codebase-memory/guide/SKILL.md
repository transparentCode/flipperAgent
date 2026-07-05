---
name: codebase-memory-guide
description: Reference for codebase-memory-mcp tools, schema, and best practices. Use when you need to know which tool to use or how to query the knowledge graph.
user-invocable: true
---

# Codebase Memory — Guide

## Tools

| Tool | Purpose | Example |
|------|---------|---------|
| `index_repository` | Index or re-index the repo | `index_repository({"repo_path": "/Users/aloobhujia/flipperAgent"})` |
| `list_projects` | List indexed projects | `list_projects({})` |
| `search_graph` | Find symbols by name/label/file | `search_graph({"name_pattern": ".*Handler.*", "label": "Function"})` |
| `search_code` | Graph-augmented grep | `search_code({"query": "auth validation"})` |
| `trace_path` | Blast radius / call chain | `trace_path({"function_name": "X", "direction": "both"})` |
| `get_code_snippet` | Read source for a symbol | `get_code_snippet({"qualified_name": "flipperAgent.src.libs.X"})` |
| `get_architecture` | Codebase overview | `get_architecture({})` |
| `detect_changes` | Pre-commit scope check | `detect_changes({})` |
| `query_graph` | Custom Cypher-like queries | `query_graph({"query": "MATCH (f:Function) RETURN f.name LIMIT 5"})` |

## Node Labels
`Project`, `Package`, `Folder`, `File`, `Module`, `Class`, `Function`, `Method`, `Interface`, `Enum`, `Type`, `Route`, `Resource`

## Edge Types
`CONTAINS_PACKAGE`, `CONTAINS_FOLDER`, `CONTAINS_FILE`, `DEFINES`, `DEFINES_METHOD`, `IMPORTS`, `CALLS`, `HTTP_CALLS`, `ASYNC_CALLS`, `IMPLEMENTS`, `HANDLES`, `USAGE`, `CONFIGURES`, `WRITES`, `MEMBER_OF`, `TESTS`, `USES_TYPE`, `FILE_CHANGES_WITH`

## Best Practices
- Run `index_repository` after large refactors or before deep analysis.
- Use `search_graph` before `search_code` when you know the symbol type.
- Use `trace_path` upstream before editing; use downstream to understand side effects.
- Use `detect_changes` before committing to verify scope.
