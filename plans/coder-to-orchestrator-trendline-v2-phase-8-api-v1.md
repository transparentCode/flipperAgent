---
goal: align provider results with discovery snapshots and expose minimal discovery API
stage: coder-to-orchestrator
date_created: 2026-07-23
last_updated: 2026-07-23
owner: quant-coder
status: Ready
source_agent: quant-coder
target_agent: quant-orchestrator
tags: [handoff, quant, trendline-v2, phase-8, discovery-api]
---

# Trendline V2 Phase 8 API Handoff

## 1. State

Final state: `READY_FOR_ORCHESTRATOR_REVIEW`

Base commit: `23528b06a8896892ea81df5049deb18412e43202`
Branch: `feature/trendline-v2-phase-8-api-v1`
Working tree: intentionally uncommitted Phase 8 changes only

Phase 8A snapshot alignment and minimal discovery API are implemented. No
provider algorithm, provider configuration field, benchmark, YAML activation,
viewer, tracking, storage, Regime integration, merge, or push was added.

## 2. Changed files

Runtime:

- `src/libs/models/trendline_v2/api.py`
- `src/libs/models/trendline_v2/__init__.py`
- `src/libs/models/trendline_v2/domain/enums.py`
- `src/libs/models/trendline_v2/discovery/contracts.py`
- `src/libs/models/trendline_v2/input/frame.py`

Tests:

- `tests/models/trendline_v2/test_api.py`

Handoff:

- `plans/coder-to-orchestrator-trendline-v2-phase-8-api-v1.md`

No `.agents/`, `.codex/`, `.github/`, `mcp/`, `AGENTS.md`, `.vscode/`, config,
legacy trendline, or runtime application files changed.

## 3. Public API

```python
def discover_trendlines(
    frame: ConfirmedOHLCVFrame,
    *,
    config: ResolvedTrendlineV2Config,
    provider_config: ConfirmedExtremaPairConfig,
) -> ProviderResult:
```

The API rejects raw DataFrames, mappings, unresolved configuration, provider
instances, provider names, separate asset/timeframe values, and YAML paths.
It constructs one immutable `ProviderInput`, one `ProviderRequest`, and calls
`ConfirmedExtremaPairProvider().generate(request)` exactly once.

Only `discover_trendlines` is exported from `libs.models.trendline_v2`.

## 4. Frame conversion

The API consumes `frame.arrays()` and forwards:

- `asset`, `timeframe`, `observed_at`, `confirmed_through` from the frame;
- timestamps as integer epoch nanoseconds;
- open, high, low, close, and volume as float tuples.

No resampling, timestamp reconstruction, rounding, future truncation, filling,
or mutation occurs at the API boundary.

`ConfirmedOHLCVFrame.arrays()` now normalizes pandas UTC indexes to epoch
nanoseconds before returning arrays. This is required because current pandas
may retain microsecond-backed UTC indexes while `ProviderInput` and the
approved provider contract use epoch nanoseconds. Existing input identity and
frame serialization remain unchanged.

## 5. Snapshot mapping

`ProviderResult.to_snapshot()` is explicit and fail-closed:

| Provider outcome | Snapshot outcome |
| --- | --- |
| `SUCCESS` | `VALID`, reason `None` |
| `ABSTAINED / INSUFFICIENT_INPUT` | `ABSTAINED / INSUFFICIENT_DATA` |
| `ABSTAINED / NO_CANDIDATES` | `ABSTAINED / NO_CANDIDATES` |
| `ABSTAINED / INVALID_INPUT` | `ABSTAINED / INVALID_INPUT` |
| `ABSTAINED / CONFIGURATION_ERROR` | `ABSTAINED / CONFIGURATION_ERROR` |
| `ABSTAINED / HYPOTHESIS_LIMIT_EXCEEDED` | `ABSTAINED / HYPOTHESIS_LIMIT_EXCEEDED` |
| `ABSTAINED / OUTPUT_LIMIT_EXCEEDED` | `ABSTAINED / OUTPUT_LIMIT_EXCEEDED` |
| `FAILED / PROVIDER_FAILURE` | `FAILED / PROVIDER_FAILURE` |

Unsupported status/reason combinations raise `ContractValidationError`.
`DiscoverySnapshot` receives request input/config identities and executing
provider identity. Provider detail and provider evidence do not enter snapshot
content or identity. Provider-specific evidence remains complete and ordered
on `ProviderResult`.

## 6. Ordering guarantees

`ProviderResult.candidates` and `ProviderResult.evidence` are never reordered.
`to_snapshot()` sorts only its new candidate tuple by `(role.value,
candidate_id)`, satisfying the snapshot contract. Candidate/evidence
one-to-one ordering remains validated by the existing `ProviderResult`
contract.

## 7. Validation evidence

Focused API suite:

- `23 passed`

Trendline V2 suite:

- `112 passed` (89 approved Phase 7A baseline plus 23 Phase 8 tests)

Protected Trendline Family suite:

- `399 passed`

Phase 7A benchmark harness regression:

- `4 passed`

Static checks:

- Ruff: passed for V2 runtime, V2 tests, and benchmark script
- compileall: passed for V2 runtime and benchmark script
- `git diff --check`: passed

Coverage includes manual-path byte-equivalent parity, all supported abstention
and failure mappings, snapshot ordering and repeated IDs, provider evidence
retention, malformed outcome fail-closed behavior, frame causality with
malformed future rows, frame immutability, sub-microsecond provider abstention,
strict input types, and forbidden/implicit configuration boundaries.

## 8. Code intelligence

Codebase-memory reindex completed on branch head `23528b0` with non-zero indexes:

- `flipperAgent-src`: 22,501 nodes / 116,827 edges
- `flipperAgent-tests`: 5,395 nodes / 22,668 edges
- `flipperAgent-scripts`: 742 nodes / 3,235 edges
- `flipperAgent-plans`: 5,105 nodes / 5,102 edges
- `flipperAgent-conductor`: 196 nodes / 981 edges
- `flipperAgent-docs`: 433 nodes / 431 edges

GitNexus reindex also completed successfully: 47,113 nodes / 77,853 edges,
with 85 large generated files skipped by its existing size policy.

Post-index graph confirms `discover_trendlines`,
`ProviderResult.to_snapshot`, and epoch-nanosecond `ConfirmedOHLCVArrays`.

## 9. Residual risks and boundaries

- Provider selection remains hard-coded to the approved confirmed-extrema pair
  reference provider. No registry or fallback was introduced.
- Provider v1 remains pure Python and unprofiled beyond approved Phase 7A
  evidence; Phase 7B Numba remains unauthorized.
- No provider configuration values were added or activated in canonical YAML.
- No TVLC viewer, parameter sensitivity, tracking, storage, MTF, Regime, or
  runtime integration work was performed.
- Changes are not committed, merged, or pushed. Orchestrator review and commit
  decision remain pending.
