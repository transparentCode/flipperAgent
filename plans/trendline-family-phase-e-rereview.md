# Trendline Family Model — Phase E Re-review

## Current Mode

Quant re-review.

## Decision

**Revision required. Phase F remains blocked.**

The prior Phase-E remediation correctly fixes optional import isolation, enabled-configuration diagnostics, post-persistence feature-projection failures, generic programming-error classification, pipeline fallback payloads, real trend-gate invariance, and missing/invalid timestamp atomicity.

Three uncovered runtime invariants still prevent final approval.

---

## Validation Reproduced

### Trendline-family plus RegimeV2 adapter suites

```text
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/models/trendline_family \
  tests/models/regime_v2/adapters -q

191 passed
```

### Active RegimeV2, legacy trendline adapter, selection and signal suites

```text
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_regime_v2.py \
  tests/test_regime_v2_trendline_feature_producer.py \
  tests/test_selection_layer.py \
  tests/signals -q

147 passed, 1 unrelated deprecation warning
```

### Narrow lint and compilation

```text
ruff check \
  src/libs/models/regime_v2/adapters/trendline_family_feature_producer.py \
  src/libs/models/regime_v2/adapters/__init__.py \
  src/apps/signal_app/pipeline/regime.py \
  tests/models/regime_v2/adapters

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

Codebase-memory:

```text
Users-aloobhujia-flipperAgent
40,017 nodes
126,956 edges
status: ready
```

The known unrelated root collection failure involving `apps.tv_scraper` and the pre-existing broad RegimeV2 Ruff findings remain outside Phase E.

---

# Findings

## P0 — Projected trigger lanes update the shadow one trigger late

Relevant flow:

```text
SignalRuntimeWorker._process_projected_candle
-> RegimeFeaturePipeline.enrich
-> _attach_trendline_family_shadow
-> SignalRuntimeWorker._commit_projected_bar
```

The projected decision bar is committed to `RegimeFeaturePipeline` only **after** shadow enrichment.

Consequences:

1. Bootstrap creates a valid family snapshot at the latest confirmed decision bar.
2. Every projected trigger before the next committed decision bar calls the family API again with the same confirmed timestamp.
3. The tracker rejects it with `update timestamp must advance beyond repository head`.
4. The trigger that actually closes the new decision bar still publishes an invalid shadow payload because the bar has not yet been committed.
5. `_commit_projected_bar` appends the closed decision bar after feature generation.
6. The next trigger, which belongs to an incomplete new decision bar, advances the family repository using the previously closed decision bar.

Independent real-worker reproduction:

```text
bootstrap:
  valid = true
  family timestamp = 2023-11-14T20:00:00Z

decision-bar close feature vector:
  valid = false
  error_reason = trendlinefamilyupdateerror
  family timestamp = None

next incomplete projected feature vector:
  valid = true
  family timestamp = 2023-11-15T00:00:00Z
  ctx_transport.decision_bar_closed = false
```

A simpler repeated-enrich reproduction also shows the root issue:

```text
first enrich with confirmed history:
  valid = true

second enrich without a new confirmed bar:
  valid = false
  error_type = family_contract_error
  error_reason = trendlinefamilyupdateerror
```

This violates:

- confirmed-bar-only Phase-E execution;
- truthful row-level shadow timing;
- expected shadow coverage;
- state advancement on the bar that actually caused the update;
- the claim that no incomplete-bar path was introduced.

### Required behavior

For direct decision-timeframe lanes:

- continue updating once after each newly appended confirmed bar.

For projected/trigger lanes:

- do not call `update_trendline_families()` on incomplete projected bars;
- do not call it repeatedly for an already-published confirmed timestamp;
- when a projected decision bar becomes confirmed, include that bar in the shadow frame and advance the family repository exactly once **before the same close feature vector is finalized**;
- attach that valid new shadow payload to the decision-bar-close feature vector;
- on subsequent incomplete triggers, attach the latest cached shadow payload or an explicit non-error no-update payload without advancing repository state;
- preserve active RegimeV2 evaluation order and outputs.

Do not solve this by appending the projected bar to the shared active `_price_history` earlier if that changes active RegimeV2 decisions. Use a shadow-specific confirmed-bar seam, frame override, or equivalent bounded mechanism.

### Required tests

Add actual `SignalRuntimeWorker` projected-lane tests proving:

- bootstrap creates one valid head;
- intermediate incomplete triggers perform zero family updates;
- the closing trigger advances the family head exactly once;
- the close vector contains the new valid shadow snapshot;
- the next incomplete trigger does not advance again;
- `trendline_family_timestamp` equals the latest confirmed decision-bar timestamp;
- provider/repository call counts are exact;
- active RegimeV2 output remains byte-identical to the baseline projected lane.

---

## P1 — Latency capture is still outside a reliable fail-soft fallback

Location:

```text
TrendlineFamilyFeatureProducer.analyze
```

`started_at = self._clock()` executes before the `try` block.

After an exception inside the transaction, both exception handlers call the clock again while constructing the failure payload:

```python
_elapsed_ms(started_at, self._clock())
```

If the clock fails, the failure handler itself raises.

Independent reproduction with a clock that succeeds once and then raises:

```text
family update persisted
success latency read raised RuntimeError
outer unexpected handler caught it
failure latency read raised RuntimeError again
result: RuntimeError escaped
```

This contradicts the claimed whole-transaction fail-soft boundary covering latency and payload creation.

### Required behavior

- move the initial clock read inside the protected transaction or use a safe start helper;
- use a no-throw elapsed-time helper in success and failure paths;
- if timing cannot be measured, return a deterministic non-negative fallback such as `0.0`;
- never let the injected or production clock break active RegimeV2 processing;
- preserve truthful repository-head reporting even when timing fails.

### Required tests

- clock fails on the initial read;
- clock fails after a successful persistence;
- clock fails while handling a canonical family error;
- no exception escapes;
- payload remains `unexpected_error` where appropriate;
- repository heads and `state_advanced` remain truthful;
- latency is deterministic and non-negative.

---

## P1 — A stale input shadow namespace can leak into active RegimeV2

Location:

```text
RegimeFeaturePipeline.enrich
RegimeFeaturePipeline._attach_regime_v2
```

The pipeline appends the newly generated shadow after active RegimeV2, which is correct for fresh inputs. However, it does not remove a pre-existing `trendline_family_shadow` key from the input feature mapping before calling active RegimeV2.

Independent reproduction:

```text
input features:
  trendline_family_shadow = {stale: leak}

active RegimeV2 latest_features:
  trendline_family_shadow = {stale: leak}
```

The final output later overwrites the namespace with the new shadow payload, hiding the fact that active RegimeV2 already received it.

This violates the categorical isolation requirement that active RegimeV2 never receives family-shadow fields.

### Required behavior

Treat `trendline_family_shadow` as a reserved output-only namespace:

- remove it from the copied input before any active orchestrator, classifier or RegimeV2 evaluation;
- attach only the freshly generated/cached shadow payload after active evaluation;
- do not mutate the caller’s input mapping;
- preserve all other feature keys byte-for-byte.

### Required tests

- pass a stale shadow namespace into `enrich()`;
- active RegimeV2 receives no shadow key;
- active output equals the baseline without that stale key;
- final output contains only the newly generated shadow payload;
- caller input remains unchanged.

---

# Verified Remediations

The following prior blockers are resolved and must not be redesigned:

- shared RegimeV2 adapters no longer eagerly import the optional family adapter;
- active RegimeV2 and legacy trendline producers import when the optional family module is blocked;
- disabled/missing shadow config avoids optional adapter import and family work;
- explicitly enabled invalid/import/construction failures retain a diagnostic producer and namespace;
- feature projection failures after persistence return `unexpected_error` with truthful before/after heads and `state_advanced=true`;
- provider `TypeError`, `ValueError` and `RuntimeError` are classified as unexpected programming failures;
- pipeline-level producer exceptions attach a structured failure payload;
- missing, NaN and infinite active-shadow timestamps fail before history mutation;
- duplicate/non-monotonic shadow timestamps produce explicit invalid evidence;
- real enabled `regime_v2_trend_gate` decisions are invariant;
- legacy `trendline` evidence remains unchanged;
- repository lineage, replay, future-row invariance and artifact aggregation remain green;
- Phase F was not started.

---

# Blast Radius

Expected correction scope:

```text
src/libs/models/regime_v2/adapters/trendline_family_feature_producer.py
src/apps/signal_app/pipeline/regime.py
src/apps/signal_app/runtime/worker.py
tests/models/regime_v2/adapters/
tests/signals/
```

No change is required in:

- trendline-family geometry, matching, lifecycle or interaction contracts;
- RegimeV2 probability logic;
- overlays or selection policy;
- MoE or MTF composition;
- risk or execution;
- legacy trendline producer behavior.

---

# Codex Remediation Handoff

```text
Apply the final Phase-E remediation only using:

- plans/trendline-family-phase-e-rereview.md
- plans/trendline-family-phase-e-review.md
- plans/trendline-family-phase-d-approval.md
- plans/trendline-family-codex-phase-execution-plan.md
- plans/trendline-family-model-architecture-plan.md

Do not start Phase F.

Fix exactly these remaining issues:

1. Projected trigger lanes must update the family shadow exactly once on
   the confirmed decision-bar close, attach that valid payload to the
   same close vector, and perform zero updates on incomplete triggers.
   Do not change active RegimeV2 outputs or move unconfirmed data into
   the family model.

2. Make clock/latency capture fully no-throw across initial, success and
   failure paths. A clock failure must never escape the shadow adapter.

3. Treat trendline_family_shadow as a reserved output-only namespace.
   Strip any stale input value before active RegimeV2 evaluation and
   attach only the newly generated or cached payload afterward.

Add adversarial tests listed in the re-review, including a real
SignalRuntimeWorker projected-lane sequence and exact repository/provider
call counts.

Preserve all already-approved optional-import, config-failure,
post-persistence, timestamp, replay, artifact and decision-invariance
behavior.

Run:

PYTHONPATH=src .venv/bin/python -m pytest \
  tests/models/trendline_family \
  tests/models/regime_v2/adapters -q

PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_regime_v2.py \
  tests/test_regime_v2_trendline_feature_producer.py \
  tests/test_selection_layer.py \
  tests/signals -q

ruff check the changed Phase-E production and test files.

compileall the changed adapter and signal-pipeline modules.

git diff --check.

Reindex codebase-memory and report project, nodes, edges and status.

Return the mandatory completion report and stop.
```

---

## Approval Status

**Request changes. Phase F remains blocked pending one final Phase-E approval review.**
