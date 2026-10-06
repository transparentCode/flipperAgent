---
name: phase-handoff
description: Persist concise durable state before clearing context or moving to the next flipperAgent workflow phase.
disable-model-invocation: true
---

Create or update the appropriate durable handoff for $ARGUMENTS under `plans/`, following the canonical stage naming, front matter, and section guidance in `.agents/skills/quant-orchestrator/`.

Write only information that the next owner cannot safely reconstruct cheaply from the checkout:

- objective and current workflow state;
- approved scope and explicit non-goals;
- verified decisions and invariants;
- affected files/symbols/flows;
- acceptance criteria;
- exact validation/evidence already completed;
- blockers, unresolved questions, and residual risk;
- the next authorized action.

Do not dump chat history, raw logs, full diffs, or speculative notes. Verify the handoff against the live checkout before saving it. Preserve prior handoffs rather than overwriting historical evidence.
