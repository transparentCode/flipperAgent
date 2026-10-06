---
name: implementation-review
description: Perform a fresh, read-only two-pass review of an implementation against its approved handoff and actual diff.
context: fork
agent: quant-architect
background: false
disable-model-invocation: true
---

Review $ARGUMENTS against the applicable approved handoff under `plans/`.

Pass 1: verify contract compliance, scope, actual diff, tests, configuration behavior, and supplied evidence.

Pass 2: independently challenge assumptions, edge cases, APIs/schemas, failure paths, concurrency/resource handling, security, compatibility, causal/PIT correctness, test quality, and over/under-engineering.

Report findings by severity with concrete file/symbol references. Distinguish blocking defects from residual risk. Do not edit files and do not repeat expensive execution unless a finding requires targeted verification.
