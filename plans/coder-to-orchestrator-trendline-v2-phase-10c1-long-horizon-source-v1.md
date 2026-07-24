# Coder-to-Orchestrator: Trendline V2 Phase 10C.1

## Status

`READY_FOR_ORCHESTRATOR_REVIEW`

Phase 10C.1 froze source data only. No provider, evaluator, selection,
tracking, runtime, YAML, viewer, or model code was changed.

## 1. Branch and base

```text
Branch: research/trendline-v2-phase-10c1-long-horizon-source-v1
Base commit: cefdf47c69d6d2c1567778eca796e988d49eb69e
Working tree: exactly three untracked implementation/handoff files
Commit: not authorized
Merge: not authorized
Push: not authorized
```

## 2. Changed files

```text
scripts/freeze_trendline_v2_long_horizon_source.py
tests/scripts/test_trendline_v2_long_horizon_source.py
plans/coder-to-orchestrator-trendline-v2-phase-10c1-long-horizon-source-v1.md
```

No other Git files changed. The generated bundle is outside the repository.

## 3. Source contract

Namespace:

```text
trendline_v2_phase_10c1_long_horizon_source_contract
```

Schema:

```text
trendline_v2_phase_10c1_long_horizon_source_v1_contract
```

Canonical contract identity:

```text
136215cc9d14b471eac40439dad143987e1738ae4b7365307bc87a2f0c752eae
```

The contract binds `BTCUSDT/4h`, the two raw source components, expected
1,458 rows, 14,400-second interval, strict continuity, all-complete rows,
Decimal-to-float-once parsing, typed columns, and downstream-artifact
quarantine.

## 4. Source components

| Component | Repository source | SHA-256 | Rows | Range |
| --- | --- | --- | ---: | --- |
| `btcusdt_4h_20250801_20251201_candidate_geometry_v2` | `artifacts/trendline_family_candidate_trials/btcusdt_4h_20250801_20251201_candidate_geometry_v2/input/normalized_ohlcv.csv` | `b8590c34400042fe8e38c23ac0d01b8d26916f2b0d5a6bed4f4b51d208d0a150` | 732 | `2025-08-01T00:00:00Z` to `2025-11-30T20:00:00Z` |
| `btcusdt_4h_20251201_20260401_saturating_quality_v1` | `artifacts/trendline_family_saturating_quality_trials/btcusdt_4h_20251201_20260401_saturating_quality_v1/input/normalized_ohlcv.csv` | `2be2f31fafef8188cf936326a43cbcc926ac4320a72658ed9977c403a98c1c42` | 726 | `2025-12-01T00:00:00Z` to `2026-03-31T20:00:00Z` |

The second component is used as raw CSV bytes only. The exact quarantine
notice is persisted in `quarantine_notice.json`:

> The December 2025–April 2026 normalized CSV is reused only as byte-bound raw source material. No validation, holdout, frozen-finalist, metric or REJECT_HOLDOUT_GATE conclusion from its original trial is admitted into Trendline V2 evidence.

No old candidate stream, trial result, holdout, finalist, metric, or
`REJECT_HOLDOUT_GATE` conclusion was read or reused.

## 5. Parsing and causal validation

The runner uses only standard-library `csv` and `decimal.Decimal`; it does
not use pandas. Numeric source text is parsed as finite `Decimal`, converted
to `float` once, and passed into canonical `ProviderInput`. It validates the
exact headers, UTC whole-second timestamps, complete rows, strict ordering,
exact component boundaries, 4h continuity, finite OHLCV values, candle
bounds, non-negative volume and non-negative taker-buy-base.

The combined source is:

```text
Asset: BTCUSDT
Timeframe: 4h
Rows: 1458
First timestamp: 2025-08-01T00:00:00Z
Last timestamp: 2026-03-31T20:00:00Z
Observed at: 2026-04-01T00:00:00Z
Confirmed through: 2026-04-01T00:00:00Z
Interval: 14400 seconds
Duration: 243 days
Lookback: 122 days
Gaps: 0
Duplicates: 0
Incomplete rows: 0
```

## 6. Canonical typed input

The persisted `ProviderInput` is independently reloaded and reconstructed
from JSON. The identity and complete payload round-trip exactly:

```text
input_identity:
6397fc215f0c9d2fc7c6cdf1fe44e60e5530d7fef2c040cce2731661a5657a4c
```

The identity is newly derived from this combined typed input. It is not any
identity from either earlier trial.

## 7. Published bundle

Output root:

```text
/tmp/trendline_v2_phase10c1_long_horizon_source/20250801_20260401/
```

Decision:

```text
LONG_HORIZON_SOURCE_READY_FOR_EVICTION_REPLAY
decision_id: 086d502cf29ea0d41bae42ecf776749540750bce81bfafd129407a65909eab1a
decision.json SHA-256: 74ede8acece6486010b319a739173230112057ead69fe356591e722069d15455
```

Manifest:

```text
manifest_id: 5b8876f61aef2adcc00a0f3c4f22c6ee8bad83bc9bd27fd7ccff58c1fc8ff9a9
manifest.json SHA-256: 097780699fe6b0dc86d7894f0e5cffc8f9586da14a7b0a6f616be344c8dc9c59
member_count: 8
member_inventory_sha256: 44afe5019bc787233f79c3238edcdb526fce5b11413872435ab3f022f2c5e262
output inventory: 872bffa5aa232bfbeac2788c4575a8e73b344476c75cfedb67b8014bc82b550f
```

The bundle has 9 files total and 8 manifest members:

| Relative path | Bytes | SHA-256 |
| --- | ---: | --- |
| `components/btcusdt_4h_20250801_20251201.csv` | 83,644 | `b8590c34400042fe8e38c23ac0d01b8d26916f2b0d5a6bed4f4b51d208d0a150` |
| `components/btcusdt_4h_20251201_20260401.csv` | 90,067 | `2be2f31fafef8188cf936326a43cbcc926ac4320a72658ed9977c403a98c1c42` |
| `decision.json` | 1,176 | `74ede8acece6486010b319a739173230112057ead69fe356591e722069d15455` |
| `provider_input.json` | 92,878 | `0db01942f2d2a92588e794f90509bdc400fbe7f7a475656b2cefb9f45b5212e3` |
| `quarantine_notice.json` | 489 | `d8753dbea1f06f636715135208c4560e5fb393e0999a7dd3de44645b79fd3123` |
| `source_audit.json` | 1,620 | `77cb74ba688ee827d3e62ede31e4f62fac9de40efc6cc9725c3066dcc83038ce` |
| `source_contract.json` | 1,790 | `8e31daa651ce0ffee78391c9f71890b39394d2ea4d93762039ab4d1f036b07a6` |
| `source_summary.csv` | 763 | `d739c022466f3173672eb4d2c1b2bce7536905e28cb1b7dec3f5961b305c34cc` |

## 8. Immutability and verifier evidence

The runner verifies repository component hashes before reading, verifies
byte-identical copied components, reparses both copies, reconstructs the
typed input, verifies the source summary and quarantine notice, recomputes
the decision and manifest, and rejects forged/rebound input or quarantine
claims. Publication uses a temporary staging directory and atomic rename;
existing output is never overwritten.

```text
source_immutability_verified: true
component copies byte-identical: true
provider executions: 0
network requests: 0
```

The `--freeze-source` path requires both the CLI flag and
`TRENDLINE_V2_ALLOW_PHASE10C1_SOURCE_FREEZE=1`. The `--verify` path is
read-only and requires neither.

## 9. Final verifier remediation

The verifier now reads JSON as bytes, rejects duplicate/non-finite values,
and requires every JSON member's bytes to equal canonical serialization.
Pretty-printed, reordered, and whitespace-modified JSON remains rejected
even after manifest rebinding.

`_source_fingerprints()` now compares each source digest with its declared
`ComponentSpec.expected_sha256` before `_build_source_data()` or component
parsing. Source drift therefore fails before any normalization or copying.

External verification pins the exact contract, input, decision, manifest and
output-inventory identities, plus both component-copy hashes and byte
equality. The existing bundle was not regenerated.

## 10. Validation

```text
Hermetic focused suite:       38 passed, 1 skipped
External artifact suite:      39 passed
Trendline V2 + viewer:       215 passed
Trendline Family:            400 passed
Benchmark harness:             4 passed
Frontend npm test:            13 passed
Frontend npm audit:             0 vulnerabilities
Ruff:                          passed
compileall:                   passed
git diff --check:             passed
CLI --verify:                 passed read-only
Frozen artifact bytes:        unchanged, all 9 files
Output inventory:             872bffa5aa232bfbeac2788c4575a8e73b344476c75cfedb67b8014bc82b550f
```

The focused suite covers contract identity mutation, dual generation guard,
early source-hash drift rejection, source/header/timestamp/continuity/
completeness/OHLCV validation, Decimal conversion, JSON identity round-trip,
canonical-byte enforcement, source and copy immutability, atomic publication,
manifest rebinding attacks, no provider/network imports or calls, and exact
external artifact identity.

## 11. Index and limitations

Codebase-memory reindex completed after remediation with non-zero indexes:

```text
src:       22716 nodes / 118051 edges
tests:      5533 nodes / 23253 edges
scripts:   1481 nodes / 6606 edges
plans:     5273 nodes / 5257 edges
conductor:  196 nodes / 981 edges
docs:       433 nodes / 431 edges
```

GitNexus indexed successfully but retains stale branch metadata; its index is
not approval evidence. GitNexus FTS is unavailable in this environment; that
does not affect executable source or artifact validation.

This is source qualification only. It does not establish provider quality,
candidate density, family persistence, eviction behavior, trading utility,
or production readiness. No runtime configuration was written.

## 12. Next boundary

Phase 10C.2 may, after explicit approval, replay exact rolling-lookback
eviction over the five approved monthly checkpoints. It is not implemented
or authorized by this handoff.
