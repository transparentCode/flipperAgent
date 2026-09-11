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

1. Call list_projects and select projects by root_path covering the task files.
2. Call index_status before relying on graph freshness.
3. Include project in every project-scoped request.
4. Use the observed live schema rather than README examples when fields differ.
5. Verify important results and negative claims against source, tests, pagination,
   skipped/excluded paths, and index generation.

## Component routing and coverage

Discover the catalog live rather than copying its names/count into agent prompts.
For example, `flipperAgent-apps` covers `/workspace/src/apps`, and
`flipperAgent-src-libs-models-sr_v2` covers that model; verify both before use.
Tests, scripts, and configs may be separate projects.

Map `/workspace` to the mounted primary checkout. Its graph does not certify an
isolated worktree. Compare index status, HEAD, dirty changes, and actual source;
equal HEAD alone does not imply identical working trees.

For a model-to-application change, query both projects and inspect shared contracts
and call sites directly. Cross-project Python imports/calls may be absent from
trace results; use source or authorized GitNexus escalation. Resolve snippet names
from search_graph within the same project.

Fast mode can exclude paths even with skipped_count zero: check excluded paths
separately. Integration/e2e tests, fixtures, docs, scripts, generated and ignored
files may be absent. Use an existing narrower index or direct inspection; a query
gap does not authorize indexing.

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

Use `.agents/skills/codebase-memory/cli/SKILL.md` for missing client discovery/status
tools or explicitly authorized indexing. The HTTP helper needs a reachable adapter;
operator indexing uses container CLIs with MCP_ALLOW_INDEX=1 and does not relax
read-only adapter permissions.
