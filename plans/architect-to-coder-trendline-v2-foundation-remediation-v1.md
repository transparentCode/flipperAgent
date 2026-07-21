# Architect-to-Coder: Trendline V2 Foundation Remediation V1

## Objective

Remediate the independent review blockers in the existing Trendline V2
foundation before Phase 5 provider selection. Preserve the lean package and
make no algorithmic or runtime expansion.

## Workspace and Ownership

Work only in `/Users/aloobhujia/flipperAgent-trendline-v2-foundation` on the
current feature branch. Preserve unrelated changes. The canonical scope is
`src/libs/models/trendline_v2/`, `configs/trendline_v2.yaml`, and
`tests/models/trendline_v2/`, plus this handoff.

## Required Changes

1. Make `ConfirmedOHLCVFrame` causal at the boundary: validate enough index
   structure to select `index <= confirmed_through`, slice first, then validate
   numeric values, finite values, OHLC relationships, volume, uniqueness and
   ordering only on the causal prefix. Future NaN, infinity, invalid OHLC,
   negative volume, duplicate timestamps, and out-of-order timestamps must not
   change a fixed historical result.
2. Replace metadata-only provider input with an explicit immutable input
   boundary. `ProviderRequest` must expose the normalized causal OHLCV values
   and the resolved configuration object to `generate`; request identities must
   derive from those actual objects, not caller-supplied independent hashes.
   Add a typed `ProviderReason` enum and optional operational detail. Preserve
   explicit status/content consistency and reject malformed requests/results.
3. Make candidate evidence provider-neutral. Remove geometry endpoint and
   exact anchor-price requirements from `LineCandidate`; geometry is emitted
   line geometry and anchors are supporting market evidence. Retain only
   universal causal evidence with explicit units/definitions. Bind candidate
   identity and snapshot validation to asset and timeframe.
4. Remove `runtime.backend` and `runtime.debug` from the V2 configuration
   contract, resolver, field policy, YAML and tests. Do not add replacement
   parameters.
5. Add AST dependency tests covering every relative and absolute import edge
   among V2 `domain`, `input`, `configuration`, and `discovery`; retain the
   legacy-package and YAML-read boundary tests. No V2 runtime module may import
   old trendline packages, research/optimization, or an invalid sibling layer.

## Non-goals

Do not add a provider, registry, kernels, pathfinding/Hough logic, tracking,
matching, lifecycle behavior, interactions, MTF, RegimeV2, signal/selection,
research evaluation, optimization, persistence, or new configuration fields.
Do not modify `src/libs/trendlines/`, `app/trendlines/`,
`src/libs/models/trendlines_old/`, or unrelated packages.

## Acceptance Criteria

- Fixed-prefix output and identity are invariant to all malformed future-row
  cases listed above.
- A provider can implement discovery using only `ProviderRequest.input_data`
  and `ProviderRequest.config`, with no hidden state or globals.
- Provider reason codes are typed and expected abstention/failure states are
  explicit.
- Candidates with valid supporting anchors and independent geometry are valid;
  candidate IDs differ across asset/timeframe and snapshots reject mismatches.
- Configuration has only the approved model fields and retains deterministic
  semantic identity/serialization parity.
- AST tests enforce the complete approved dependency matrix.

## Validation

Run from the feature worktree:

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/models/trendline_v2 -q
PYTHONPATH=src .venv/bin/python -m pytest tests/models/trendline_v2/test_input.py tests/models/trendline_v2/test_provider.py tests/models/trendline_v2/test_domain.py tests/models/trendline_v2/test_configuration.py -q
ruff check src/libs/models/trendline_v2 tests/models/trendline_v2
PYTHONPATH=src .venv/bin/python -m compileall -q src/libs/models/trendline_v2
git diff --check
```

Also run the protected Trendline V1 suite recorded in the prior handoff and
report its exact result. Do not commit, merge, or switch branches unless the
orchestrator explicitly authorizes it.

## Deliverable

Return `plans/coder-to-orchestrator-trendline-v2-foundation-remediation-v1.md`
with exact files changed, tests/results, dependency-boundary evidence, identity
and serialization results, residual risks, and confirmation that Phase 5 was
not started.
