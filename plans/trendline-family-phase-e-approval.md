# Trendline Family Model — Phase E Approval

## Current Mode

Quant approval.

## Approval Scope

Phase E opt-in, shadow-only RegimeV2 integration through `TrendlineFamilyFeatureProducer`, including:

- default-disabled typed shadow configuration;
- optional-import isolation from active RegimeV2 and the legacy trendline adapter;
- canonical invocation through `update_trendline_families()`;
- repository-backed family lineage and replay semantics;
- snapshot/observation-backed shadow feature projection;
- fail-soft producer, construction and pipeline boundaries;
- deterministic enabled-failure diagnostics;
- direct-bar and projected-lane confirmed-history integration;
- additive `trendline_family_shadow` artifact payloads;
- active RegimeV2 and selection-decision invariance.

## Approval Decision

**Approved. Phase F may begin.**

No unresolved Phase-E blocker remains.

## Blocking Issues

None.

## Final Remediation Verification

### Projected decision lanes

The projected runtime now has the required temporal sequence:

```text
bootstrap confirmed history
-> one family update

incomplete projected triggers
-> cached latest confirmed shadow payload
-> zero provider calls
-> zero repository writes
-> state_advanced = false

confirmed decision-bar close
-> active RegimeV2 evaluates first without shadow input
-> confirmed decision bar appends to active and family histories
-> family shadow updates exactly once
-> the same close feature vector contains the new snapshot
-> state_advanced = true

next incomplete trigger
-> cached new snapshot
-> zero additional family update
-> state_advanced = false
```

The runtime regression verifies exactly two provider calls and two repository writes across bootstrap plus one confirmed close.

### Fail-soft timing

Operational clock reads are now no-throw:

- initial timing failure returns `0.0` latency;
- success-path final timing failure returns `0.0` latency;
- expected-error timing failure returns `0.0` latency;
- post-persistence failures preserve truthful repository heads and state advancement;
- timing failures cannot escape into the active signal pipeline.

### Reserved namespace isolation

`trendline_family_shadow` is removed from copied input before any active pipeline stage.

Therefore stale or externally supplied shadow content cannot reach:

- regime snapshot analysis;
- regime classification;
- active RegimeV2;
- active overlay or selection inputs.

The producer-owned shadow namespace is attached only after active RegimeV2 evaluation.

## Phase-E Guarantees

The approved integration now guarantees:

- `TrendlineFamilyShadow.enabled` remains false by default;
- missing or disabled config performs no optional-module import and no family-model work;
- optional family-adapter failures cannot break active RegimeV2 imports;
- explicitly enabled config/import/construction failures remain visible as deterministic invalid shadow payloads;
- generic programming errors are logged and classified as `unexpected_error`;
- feature-projection failures after persistence do not escape and report truthful repository advancement;
- pipeline-level defensive failures retain the shadow namespace;
- timestamp validation occurs before active or shadow history mutation;
- non-monotonic or duplicate confirmed timestamps produce explicit invalid shadow evidence;
- direct confirmed bars update the family model once per confirmed history revision;
- projected incomplete bars never reach family tracking;
- projected confirmed closes update exactly once and on the correct output vector;
- persisted snapshots, family states and typed observations remain the only feature truth source;
- the existing `trendline` namespace remains unchanged;
- shadow features do not affect probabilities, routing, overlays, MTF, final selection, risk or execution.

## Validation Sufficiency

### Trendline-family plus RegimeV2 adapter suites

```text
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/models/trendline_family \
  tests/models/regime_v2/adapters -q

193 passed
```

### Active RegimeV2, legacy trendline, selection and signal suites

```text
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_regime_v2.py \
  tests/test_regime_v2_trendline_feature_producer.py \
  tests/test_selection_layer.py \
  tests/signals -q

148 passed
```

One unrelated OpenTelemetry deprecation warning remains.

### Static validation

```text
ruff check \
  src/libs/models/regime_v2/adapters/trendline_family_feature_producer.py \
  src/libs/models/regime_v2/adapters/__init__.py \
  src/apps/signal_app/pipeline/regime.py \
  src/apps/signal_app/pipeline/features.py \
  src/apps/signal_app/runtime/worker.py \
  tests/models/regime_v2/adapters \
  tests/signals/test_trendline_family_shadow_projected_runtime.py

All checks passed
```

```text
PYTHONPATH=src .venv/bin/python -m compileall -q \
  src/libs/models/regime_v2/adapters \
  src/apps/signal_app/pipeline

Passed
```

```text
git diff --check

Passed
```

The reported broad RegimeV2 Ruff findings and root `apps.tv_scraper` collection failure remain pre-existing and unrelated.

## Blast Radius Confirmation

Phase E is confined to:

```text
src/libs/models/regime_v2/adapters/trendline_family_feature_producer.py
src/libs/models/regime_v2/adapters/__init__.py
src/apps/signal_app/pipeline/regime.py
src/apps/signal_app/pipeline/features.py
src/apps/signal_app/runtime/worker.py
configs/models.yaml
tests/models/regime_v2/adapters/
tests/signals/test_trendline_family_shadow_projected_runtime.py
```

No legacy trendline runtime import was added to the canonical family package.

No probability model, overlay policy, MoE route, MTF composer, selection strategy, risk module or execution module was changed.

Codebase-memory:

```text
Users-aloobhujia-flipperAgent
40,068 nodes
127,208 edges
status: ready
```

## Residual Risk

Acceptable deferred risks:

- the production repository remains in-memory;
- historical-market shadow artifact inspection has not yet been run;
- long-duration runtime latency and memory behavior remain unmeasured;
- cached invalid payloads may appear on multiple emitted rows until confirmed history changes, which is acceptable for row-level artifact accounting;
- Phase F event-state calibration has not started;
- root collection and broad legacy RegimeV2 lint remain independently tracked issues.

These risks do not block Phase F implementation.

## Phase F Boundary

Phase F may convert Phase-D per-bar observations into persistent deterministic multi-bar interaction events.

Required event states:

```text
FAR
APPROACHING
IN_ZONE
REJECTING
PRESSURING
WICK_BREACHED
BODY_BREACHED
BREAK_PENDING
BREAK_CONFIRMED
RETEST_PENDING
RETEST_SUCCESS
FAILED_BREAK
ROLE_REVERSED
```

Required work:

- persistent content-addressed event IDs;
- exhaustive deterministic transition table;
- confirmation-bar logic using `interaction.close_confirmation_bars`;
- pressure duration and maximum penetration tracking;
- rejection recovery;
- bounded retest window;
- failed-break detection;
- role reversal preserving the same family ID;
- compatibility mapping to simple breakout, breakdown and bounce labels;
- deterministic replay and future-row invariance;
- runtime evidence kept separate from evaluation outcomes.

Forbidden Phase-F scope:

- multi-rail families or family corridors;
- MTF composition;
- optimization or promotion;
- probability, overlay, routing, selection, risk or execution consumption;
- repository migration/reset;
- replacement of the existing active trendline path;
- geometry identity replacement during role reversal.

Stop for review after Phase F implementation and tests.
