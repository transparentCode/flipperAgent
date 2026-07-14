# Coder → Review: Trendline-Family Research Lab Final Remediation v2

## Scope Executed

Applied only the three findings from Codex's review of the final research-lab remediation:

1. Content-addressed cross-asset comparability policy with enforced sample and metric semantics.
2. Timeframe-preserving parameter-policy identity.
3. Explicit validation sensitivity stage/metric inputs with aggregate, worst-window, and per-fold evidence traces.

No Binance adapter redesign, real-data trial, runtime integration, YAML mutation, RegimeV2 work, signal/selection change, or promotion action was performed.

## Changes Made

### Cross-asset policy and audit identity

Updated:

```text
src/libs/models/trendline_family/research_lab/contracts.py
src/libs/models/trendline_family/research_lab/tables.py
research/trendline_family_research_lab.ipynb
```

`CrossAssetComparabilityPolicy` now:

- derives `policy_id` from its complete semantic payload;
- rejects an arbitrary caller-supplied label that does not equal the derived content hash;
- binds the supported sample definition:
  - `confirmed_ohlcv_exact_window_v1`;
- binds canonical structural metric definitions:
  - `eligible_bar_count = confirmed_ohlcv_row_count_v1`;
  - `candidate_count = canonical_candidate_row_count_v1`;
  - `unique_family_count = unique_family_id_count_over_replay_v1`;
  - `family_snapshot_count = canonical_family_snapshot_row_count_v1`;
- binds minimum asset count and every coverage/comparability rule into the policy identity.

`CrossAssetComparabilityAudit` now persists the complete frozen `policy_identity`, verifies:

```text
deterministic_hash(policy_identity) == policy_id
```

and `CrossAssetComparison` requires the audit identity to equal the supplied typed policy identity.

The previously free-form `sample_definition` is no longer display-only: unsupported values reject. Metric definitions are also enforced against the exact metrics the comparison builder calculates.

### Parameter policy timeframe binding

Updated:

```text
src/libs/models/trendline_family/research_lab/replay.py
```

`parameter_policy_hash(...)` now excludes only `asset` from the resolved configuration payload. It preserves `timeframe`, so otherwise identical `1h` and `4h` policies produce different hashes.

Asset-specific resolved identities remain comparable when all non-asset semantics, including timeframe, match.

### Validation sensitivity evidence

Updated:

```text
src/libs/models/trendline_family/research_lab/plotting.py
research/trendline_family_research_lab.ipynb
```

`build_validation_sensitivity_figure(...)` now requires explicit:

```text
stage
metric
```

It rejects rows that do not match those inputs and still rejects any holdout-bearing evidence.

Every sensitivity figure now exposes:

- aggregate validation metric traces;
- persisted worst-window metric traces;
- one trace per persisted validation fold;
- fold ID;
- window result ID;
- trial ID;
- trial result ID;
- exact parameter overrides.

The notebook obtains the explicit metric from the verified Phase-I manifest objective for the explicit stage. It does not derive optimization truth from chart rows and does not use holdout evidence for tuning or ranking.

## Files Changed

```text
research/trendline_family_research_lab.ipynb
src/libs/models/trendline_family/research_lab/contracts.py
src/libs/models/trendline_family/research_lab/replay.py
src/libs/models/trendline_family/research_lab/tables.py
src/libs/models/trendline_family/research_lab/plotting.py
tests/models/trendline_family/research_lab/test_replay_tables_plotting.py
tests/models/trendline_family/research_lab/test_artifacts_and_boundaries.py
.codebase-memory/artifact.json
.codebase-memory/graph.db.zst
```

This handoff document is also new.

## Blast Radius Considered

Codebase-memory traces show:

- `parameter_policy_hash` is used only by research replay context construction and its causality replay helper;
- `build_cross_asset_comparison` has no runtime callers;
- `build_validation_sensitivity_figure` has no runtime callers;
- `run_phase_i_evaluation` still has no inbound production callers.

No runtime module imports `trendline_family.research_lab`.

## Validation Performed

### Focused research-lab tests

```text
24 passed
```

New regressions cover:

- policy ID content addressing;
- arbitrary policy-label rejection;
- unsupported sample-definition rejection;
- altered metric-definition rejection;
- complete policy identity persisted in audit;
- `1h` versus `4h` parameter-policy hash separation;
- explicit sensitivity stage mismatch rejection;
- explicit sensitivity metric mismatch rejection;
- holdout evidence rejection;
- aggregate, worst-window, and per-fold trace presence.

### Full trendline-family

```text
346 passed
```

### Trendline-family + adapters + projected runtime

```text
374 passed
```

### Active RegimeV2/selection/signals non-interference

```text
148 passed
1 existing OpenTelemetry LoggingHandler deprecation warning
```

### Static and notebook checks

```text
Ruff: passed
compileall: passed
notebook JSON: valid nbformat 4, 34 cells, outputs cleared
git diff --check: passed
forbidden/dead-control scan: passed
```

### Codebase-memory

```text
project: Users-aloobhujia-flipperAgent
nodes:   41,811
edges:   138,928
status:  ready
```

## Not Changed

- `BinanceNativeAdapter` or historical pagination;
- candidate provider, tracker, matching, rails, corridor, interaction, event, or MTF compositor semantics;
- Phase-I optimizer, objective gates, holdout semantics, or promotion rules;
- runtime YAML;
- RegimeV2 or adapters;
- signal, selection, strategy, risk, execution, or portfolio paths;
- real-market artifacts or runtime promotion.

## Review Requests

Please independently replay these exact attacks:

1. Supply an arbitrary `policy_id`; construction must reject.
2. Change sample-definition or metric-definition semantics; construction must reject.
3. Rebuild an audit with a mismatched policy identity; construction/comparison must reject.
4. Compare identical asset-specific `1h` policies; parameter hashes may match after asset exclusion.
5. Compare otherwise identical `1h` and `4h` policies; parameter hashes must differ.
6. Call sensitivity plotting without matching explicit stage or metric; it must reject.
7. Inject holdout window evidence; it must reject.
8. Verify the valid figure contains aggregate, worst-window, and per-fold traces with fold/window IDs.

## Risks or Follow-Up Items

- Cross-asset research currently supports one explicitly versioned confirmed-OHLCV sample definition and four explicitly versioned structural metrics. Adding new sample populations or metrics requires a new canonical definition/version rather than free-form text.
- This change does not authorize real-data research. Approval of the notebook/support layer remains required first.
