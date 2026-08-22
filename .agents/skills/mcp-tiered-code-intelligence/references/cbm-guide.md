# CBM Reference

This is the detailed reference for codebase-memory-mcp. The governing policy and
server selection rules live in the parent SKILL.md; this file contains schemas,
query patterns, and workflow-specific checklists.

## Live read-only surface

| Tool | Purpose | Required scope |
| --- | --- | --- |
| list_projects | Resolve indexed project identifiers | none |
| index_status | Check generation and freshness | project |
| search_graph | Find typed symbols | project |
| search_code | Graph-augmented text search | project |
| trace_path | Follow callers and callees | project, function_name, direction |
| get_code_snippet | Read a symbol's source | project, qualified_name |
| get_architecture | Get a high-level overview | project |
| detect_changes | Relate changes to indexed symbols | project |
| query_graph | Run a bounded graph query | project, query |
| get_graph_schema | Inspect available labels and edges | project |

Indexing, deletion, ADR mutation, and trace ingestion are operator actions. They
are not an agent workflow or a fallback for an empty result.

## Common preflight

1. Call list_projects and use the returned project identifier.
2. Call index_status before relying on graph freshness.
3. Include project in every project-scoped request.
4. Use the observed live schema rather than README examples when fields differ.
5. Verify important results and negative claims against source, tests, pagination,
   skipped/excluded paths, and index generation.

## Exploration

1. State one concrete question about a module, symbol, or execution flow.
2. Locate symbols with search_graph or search_code.
3. Trace inbound, outbound, or both call paths.
4. Read the relevant snippets and direct source.
5. Report files, symbols, flow, freshness, and coverage gaps.

An empty graph response means only “not found in this query.” It is never proof
that a dependency or call path does not exist.

## Debugging

1. Preserve the exact symptom, error, and reproduction context.
2. Resolve the project and check index status.
3. Search for the error or related symbols.
4. Trace inbound callers and outbound dependencies.
5. Inspect the suspect source directly.
6. Compare indexed changes when useful.
7. Validate the hypothesis with tests or a reproducible runtime check.

Report the symptom, suspect symbols/files, call chain, recent changes, hypothesis,
validation, and remaining evidence gaps.

## Impact analysis

Before changing an existing shared symbol:

1. Locate it with search_graph.
2. Trace inbound callers and outbound callees.
3. Cross-check textual references with search_code.
4. Map affected flows and classify direct versus transitive impact.
5. Use detect_changes to bound the current diff.

Treat direct callers/importers as higher risk than distant transitive dependents,
but do not assign a final severity from graph distance alone.

## Refactoring

For a rename, extraction, split, or move:

1. Resolve the project and locate the target symbol.
2. Trace both directions.
3. Cross-check all textual references.
4. Plan small behavior-preserving edits.
5. Update direct dependents through the approved coder workflow.
6. Run the touched test slice.
7. Recheck change scope and inspect the final diff.

CBM is read-only evidence. Do the refactor in the repository; never use denied
graph-maintenance operations as an editing shortcut.

## Operator CLI escape hatch

Use .agents/skills/codebase-memory-cli/SKILL.md only when the MCP service is
unavailable or an operator has explicitly authorized maintenance. Routine agent
work must use the configured MCP adapter, and indexing requires the explicit
MCP_ALLOW_INDEX=1 gate.
