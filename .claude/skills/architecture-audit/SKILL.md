---
name: architecture-audit
description: Run an evidence-backed, read-only architecture and code audit for a flipperAgent subsystem before refactoring.
context: fork
agent: quant-architect
background: false
disable-model-invocation: true
---

Audit $ARGUMENTS as a read-only pre-refactor investigation.

Follow the canonical `quant-architect` workflow. Inspect relevant production code, tests, configuration, architecture records, and current plans/handoffs. Trace runtime composition and material callers/callees. Use tiered code intelligence only as navigation/evidence support and verify findings in source.

Return:

1. current architecture and ownership boundaries;
2. verified evidence with concrete files/symbols;
3. defects and design risks, separated from hypotheses;
4. blast radius and compatibility concerns;
5. the smallest viable remediation options;
6. unresolved questions and evidence limitations.

Do not edit files, implement a refactor, or claim absence from an incomplete graph/search.
