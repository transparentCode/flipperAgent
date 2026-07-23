# Trendline V2 Provider Realignment V1

## Status

`READY_FOR_ORCHESTRATOR_REVIEW`

## Repository

- Base: `origin/main` at `5de601a529d39d847ed1c4ec269ec2131fdd249e`.
- Branch: `refactor/trendline-v2-provider-realignment-v1`.
- Worktree: `/Users/aloobhujia/flipperAgent-trendline-v2-provider-realignment`.
- No merge or push occurred.

## R1 Contract Realignment

- Removed constructor-controlled provider semantics and retained only six required
  active fields: physical lookback duration, left/right confirmation bars,
  minimum extrema per role, and the two workload limits.
- Provider-v1 semantics now live as versioned code constants. The field-policy
  surface contains only the six active fields, all unresolved and YAML-inactive.
- `ProviderResult` owns an ordered, one-to-one `LineCandidate` to
  `ConfirmedExtremaPairEvidence` binding. Evidence carries only dynamic values;
  fixed schema and policy values remain serialized code-owned invariants.

## R2 Reference Provider

- Added `ConfirmedExtremaPairProvider` as the sole provider implementation.
- It takes only `ProviderRequest` input, selects a physical UTC-duration history,
  confirms left-strict/right-nonstrict extrema, and builds exact timestamp-space
  geometry.
- Support and resistance pairs use exact intermediate candle-body rejection with
  equality accepted. Candidate and evidence order is deterministic and no quality,
  score, ranking, old-model import, network, or mutable runtime state is used.
- Pair hypotheses are counted before allocation. Hypothesis and output overflows
  abstain with typed reasons; neither path truncates the candidate set.

## Causality And Identity

- Extrema are emitted only after the full right confirmation window exists.
- Anchors encode asset, timeframe, extrema kind, source/confirmation UTC time,
  price, and provider identity. A later observed snapshot retains confirmed anchor
  identity while receiving its own observed-at-scoped candidate identity.
- Geometry and structural validation share the same UTC timestamp representation.
- Candidate and evidence IDs, ordering, and serialized result are stable for
  equivalent input sequences and repeated calls.

## Provider Output Examples

- The seven-bar confirmed-low fixture emits `SUCCESS` with three support pairs:
  source positions `(1, 3)`, `(1, 5)`, and `(3, 5)`. Its ordered evidence has
  the same candidate IDs and corresponding confirmation positions `(2, 4)`,
  `(2, 6)`, and `(4, 6)`.
- A physical lookback too short for the extrema windows returns
  `ABSTAINED / INSUFFICIENT_INPUT`; flat and monotonic fixtures do the same.
- A three-pair fixture with `max_hypotheses=2` returns
  `ABSTAINED / HYPOTHESIS_LIMIT_EXCEEDED`. The identical candidate population
  with `max_output_candidates=1` returns
  `ABSTAINED / OUTPUT_LIMIT_EXCEEDED`. Neither result contains partial output.

## Validation

```text
PYTHONPATH=src .venv/bin/python -m pytest tests/models/trendline_v2 -q -ra
73 passed

PYTHONPATH=src .venv/bin/python -m pytest tests/models/trendline_family -q -ra
399 passed

ruff check src/libs/models/trendline_v2 tests/models/trendline_v2
All checks passed

PYTHONPATH=src .venv/bin/python -m compileall -q src/libs/models/trendline_v2
Passed

git diff --check
Passed
```

Coverage includes causal confirmation, plateau selection, irregular UTC geometry,
exact-side validation, typed abstentions, workload guards, deterministic output,
active-field effects, malformed input, and prohibited-import checks.

## Commits

1. `8654307 refactor(trendline-v2): collapse premature provider scaffolding`
2. `0329402 feat(trendline-v2): implement confirmed extrema reference provider`
3. Pending this handoff/test commit: `test(trendline-v2): validate extrema provider causality`

## Protected Scope

- No YAML activation, provider registry, Numba, public discovery API, viewer,
  research/optimization, legacy trendline import, Regime integration, merge, or
  push was added.
- Changed runtime code remains under `src/libs/models/trendline_v2`; tests remain
  under `tests/models/trendline_v2`; this handoff is the only plan artifact.

## Graph Status

- `./mcp/scripts/mcp-index.sh` rebuilt codebase-memory sub-indexes after the
  final code commit: `flipperAgent-src` `22,465` nodes / `116,478` edges and
  `flipperAgent-tests` `5,335` nodes / `22,350` edges, both `indexed`.
- The wrapper's final GitNexus step could not run because optional service
  `mcp-proxy` was not running. This did not affect the completed
  codebase-memory indexes.

## Residual Risks

- The reference provider is intentionally unprofiled pure Python; Phase 7 is
  required before any performance kernel decision.
- Provider configuration scope remains unresolved and fixture-only. It is not
  canonical YAML or runtime configuration.
- Python `datetime` preserves microsecond precision. The approved exchange-style
  UTC input fixtures use millisecond-or-coarser timestamps; sub-microsecond source
  timestamps need an explicit domain-contract decision before support is claimed.

## Next Boundary

Orchestrator review only. Do not start Phase 7, 8, 8V, or 9.
