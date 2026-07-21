# Trendline V2 Program Roadmap

Trendline V2 is an independently owned, research-ready model under
`src/libs/models/trendline_v2/`. Existing trendline packages remain frozen
references and are never runtime dependencies.

## Approved Sequence

0. Program contract and repository reconnaissance.
1. Domain contracts and deterministic identity.
2. Causal confirmed-OHLCV input boundary.
3. Strict scoped configuration foundation.
4. Technique-independent provider protocol.
5. First-provider selection study.
6. First approved provider implementation.
7. Measured numeric-kernel profiling and optimization.
8. Minimal discovery API.
9. Candidate evidence and quality research.
10. Minimal family tracking.
11. Interaction observations.
12. Event lifecycle, one transition group per approval.
13. Hough challenger provider.
14. MTF composition.
15. Downstream shadow integration and migration.

## Current Authorization

Only Phases 0–4 are authorized by the Trendline V2 Clean Development Program.
The current coder handoff must stop at the foundation review gate. Provider
selection, provider implementation, kernels, discovery API, quality research,
tracking, interactions, lifecycle, MTF, and downstream integration remain
unauthorized.

## Dependency Direction

```text
api -> input, configuration, discovery, domain
discovery -> domain, configuration
input -> domain validation only
configuration -> domain validation and identity only
domain -> Python standard library only
```

No reverse dependency, compatibility package, registry, or future placeholder
folder is permitted. Every later phase requires a separate architect contract,
coder implementation, independent review, and explicit approval.

## Program Stop Conditions

Stop if a semantic value is unapproved, a parameter has no owned effect, a
fixed observed timestamp is not causal, identities are not reproducible,
protected evidence changes, an old namespace is imported, or validation is not
reproducible. A stop returns `BLOCKED` with exact evidence; no workaround is
permitted.
