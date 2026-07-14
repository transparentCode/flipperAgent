# Trendline Family Model — Phase E Review

## Current Mode

Quant review.

## Decision

**Revision required. Phase F is blocked.**

The core Phase-E design is directionally correct: the family model is default-disabled, the valid producer calls only the public `update_trendline_families()` API, persisted snapshots and observations drive the emitted feature payload, the namespace is attached after active RegimeV2 evaluation, and the existing targeted regression suites are green.

The remaining blockers are all at the optionality and fail-soft boundary. They must be corrected before Phase F or any wider runtime enablement.

---

## Validation Reproduced

### Family plus new adapter suite

```text
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/models/trendline_family \
  tests/models/regime_v2/adapters -q

177 passed
```

### Active RegimeV2, existing trendline adapter, selection and signal foundation slice

```text
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_regime_v2.py \
  tests/test_regime_v2_trendline_feature_producer.py \
  tests/test_selection_layer.py \
  tests/signals/test_signal_app_foundation.py -q

120 passed
```

### Narrow lint and compilation

```text
ruff check \
  src/libs/models/regime_v2/adapters/trendline_family_feature_producer.py \
  src/apps/signal_app/pipeline/regime.py \
  src/apps/signal_app/pipeline/features.py \
  src/apps/signal_app/runtime/worker.py \
  tests/models/regime_v2/adapters

All checks passed
```

```text
PYTHONPATH=src .venv/bin/python -m compileall -q \
  src/libs/models/regime_v2/adapters/trendline_family_feature_producer.py \
  src/apps/signal_app/pipeline/regime.py \
  src/apps/signal_app/pipeline/features.py \
  src/apps/signal_app/runtime/worker.py

Passed
```

Codebase-memory:

```text
Users-aloobhujia-flipperAgent
39,955 nodes
126,698 edges
status: ready
```

The full requested RegimeV2 Ruff result still contains the reported pre-existing unrelated violations. The root collection issue involving `apps.tv_scraper` remains unrelated.

---

# Findings

## P0 — The active RegimeV2 adapter import now hard-depends on the optional shadow package

Locations:

```text
src/libs/models/regime_v2/adapters/__init__.py
src/apps/signal_app/pipeline/regime.py:_create_regime_v2
```

`libs.models.regime_v2.adapters.__init__` eagerly imports:

```python
trendline_family_feature_producer
```

The active RegimeV2 factory imports `RegimeV2FeatureProducer` through that package:

```python
from libs.models.regime_v2.adapters import RegimeV2FeatureProducer
```

Therefore the active RegimeV2 adapter path imports the optional trendline-family shadow adapter even when `TrendlineFamilyShadow.enabled` is false.

Independent import-failure probe:

```text
simulate ImportError for libs.models.trendline_family.*
import RegimeV2FeatureProducer from libs.models.regime_v2.adapters

result:
ImportError: simulated optional family package failure
```

This violates the required shadow-only blast-radius boundary. A failure in the optional family integration must not make active RegimeV2 unavailable while the shadow feature is disabled.

### Required

Use one of these bounded designs:

1. Remove the eager trendline-family imports from `adapters/__init__.py`, and import the shadow producer directly inside `_create_trendline_family_shadow`; or
2. expose the shadow symbols through a truly lazy package mechanism that does not import them when active RegimeV2 symbols are requested.

The active factory should preferably import directly from its existing module:

```python
from libs.models.regime_v2.adapters.feature_producer import RegimeV2FeatureProducer
```

Add an import-isolation regression test proving that active RegimeV2 adapter construction/import still succeeds when the optional trendline-family shadow module is unavailable and shadow is disabled.

---

## P0 — The producer fail-soft boundary ends before feature projection

Location:

```text
src/libs/models/regime_v2/adapters/trendline_family_feature_producer.py:TrendlineFamilyFeatureProducer.analyze
```

The `try/except` surrounds `update_trendline_families()`, but the following work is outside it:

```python
_features_from_output(...)
_elapsed_ms(...)
```

Independent probe replaced `_features_from_output` with a deterministic runtime failure:

```text
projection_bug: propagated RuntimeError projection bug
repository_advanced_before_projection_failure: True
```

The family repository had already persisted the new snapshot, but the adapter raised instead of returning a structured shadow failure payload.

Inside `RegimeFeaturePipeline`, the outer attachment catch then logs and omits the `trendline_family_shadow` namespace entirely. The runtime therefore loses the audit record for a state transition that actually occurred.

### Required

Make the complete enabled invocation one outer fail-soft transaction boundary:

```text
head-before read
family API update
feature projection
latency capture
head-after read
payload creation
```

Expected canonical family errors may return normal structured failure payloads.

Unexpected adapter/projection errors must:

- be logged with exception type;
- return `trendline_family_valid = false`;
- return `trendline_family_error_type = unexpected_error`;
- preserve a stable reason based on exception class, without raw stack text in features;
- report truthful `repository_head_before` and `repository_head_after`;
- set `trendline_family_state_advanced` from the actual head comparison.

`_failure_features()` currently always sets `trendline_family_state_advanced=False`. That is only truthful for pre-persistence failures. It must accept/derive the actual value for post-persistence projection failures.

Add a regression test where projection fails after a successful save and verify:

- no exception escapes;
- repository head advanced;
- failure payload reports the new head;
- `state_advanced` is true;
- active RegimeV2 and selection still complete normally.

---

## P1 — Enabled configuration errors disappear as if the shadow were disabled

Location:

```text
src/apps/signal_app/pipeline/regime.py:_create_trendline_family_shadow
```

When config says `enabled: true` but `TrendlineFamilyShadowConfig.from_mapping()` fails, the factory logs and returns `None`.

Reproduced:

```text
input config:
  enabled: true
  unknown: 1

factory result:
  None
```

The runtime then emits no `trendline_family_shadow` namespace. Operationally this is indistinguishable from an intentionally disabled shadow producer, despite being an enabled configuration failure.

### Required

Preserve the distinction:

```text
disabled config
-> no family work; optional absence or explicit disabled payload

enabled valid config
-> normal producer

enabled invalid/unavailable config
-> producer-like fail-soft object or stored failure payload
   with shadow_enabled=true, valid=false, stable config error fields
```

Do not construct or resolve the canonical family YAML for disabled mode.

Add tests for:

- unknown shadow config key;
- invalid shadow config value;
- enabled producer import/constructor failure;
- all cases attach explicit error diagnostics and leave active decisions unchanged.

---

## P1 — The pipeline’s defensive attachment catch omits the shadow audit namespace

Location:

```text
src/apps/signal_app/pipeline/regime.py:_attach_trendline_family_shadow
```

Current behavior:

```python
except Exception:
    logger.warning(...)
```

No payload is attached.

Independent probe:

```text
shadow analyze raises RuntimeError
pipeline enrich completes
trendline_family_shadow key present: false
```

Even after the producer boundary is hardened, the pipeline’s final defensive catch should not silently erase evidence that an enabled shadow component failed.

### Required

Attach a deterministic outer-boundary failure payload under:

```text
trendline_family_shadow
```

The payload should identify:

- enabled shadow;
- invalid result;
- `unexpected_error`;
- stable exception class reason;
- zero/unknown latency as appropriate;
- no claim that repository state did or did not advance unless it can be inspected truthfully.

Prefer a shared public helper or a small producer-owned fallback contract rather than duplicating the full schema in the signal pipeline.

---

## P1 — Generic programming errors are classified as expected invalid input

Location:

```text
TrendlineFamilyFeatureProducer.analyze
```

The expected-error catch includes all `TypeError` and `ValueError`:

```python
except (ContractValidationError, OSError, TypeError, ValueError)
```

The canonical trendline-family loader, resolver, API, tracker and repository already convert expected validation failures to `ContractValidationError`.

Independent provider-bug probe:

```text
provider raises TypeError("internal provider bug")

payload:
trendline_family_error_type   = invalid_input
trendline_family_error_reason = typeerror
```

This hides a programming defect as normal input failure and does not use the unexpected-error logging path.

### Required

Narrow the expected catch to canonical expected exceptions, principally:

```text
ContractValidationError
```

and any explicitly verified external I/O exception not already wrapped by the family config loader.

Generic `TypeError`, `ValueError`, `KeyError`, `AttributeError`, and `RuntimeError` arising during provider/adaptor execution should reach the logged `unexpected_error` branch.

Add provider tests for unexpected `TypeError`, `ValueError`, and `RuntimeError`.

---

## P2 — Shadow history can silently diverge when `append_bar` receives no timestamp

Location:

```text
RegimeFeaturePipeline.append_bar
```

With the shadow enabled, active price history always advances, while family history advances only when `timestamp is not None`.

Reproduced with the public method:

```text
append_bar(..., timestamp omitted)
active history length: 1
shadow frame length passed to analyzer: 0
observed_at: None
```

All currently modified production call sites appear to pass a timestamp, so this is not independently release-blocking after the P0/P1 fixes. The seam should nevertheless fail explicitly rather than silently diverge.

Recommended:

- require timestamp when a shadow producer is present; or
- record a deterministic shadow-history input failure that is attached on the next enrichment.

Add a focused regression test.

---

## P2 — Decision-invariance tests do not yet exercise the strongest active gate

The new tests establish useful invariants:

- fake active RegimeV2 does not receive the shadow namespace;
- independent real `RegimeV2Orchestrator` output is unchanged before/after a shadow call;
- real `SelectionLayer` result is unchanged with the RegimeV2 trend gate disabled.

The selection comparison explicitly configures:

```text
regime_v2_trend_gate.enabled = false
```

This does not exercise the active overlay decision path named in the Phase-E handoff.

### Required validation improvement

Add at least one test with the existing RegimeV2 trend gate enabled and a controlled real `regime_v2` payload, proving identical:

- gate explanation/result;
- selected candidates;
- final reason/metadata excluding any intentionally additive shadow artifact;

with and without `trendline_family_shadow`.

Also add the narrowest available assertion that MTF/MoE consumers receive only the existing active RegimeV2 payload and do not inspect or flatten the new shadow namespace. No production MTF/MoE change is requested.

---

# Verified Correct Areas

The following implementation should be preserved during remediation:

- default config is disabled;
- disabled direct producer performs no repository/provider work;
- valid producer calls only `update_trendline_families()`;
- family state is accessed through `TrendlineFamilyRepository`;
- persisted snapshot diagnostics and typed observations are the emitted truth source;
- nearest-family state is selected only from active families;
- dormant-only state does not appear as nearest active support/resistance;
- repository lineage advances correctly on valid updates;
- config-lineage mismatches fail soft and preserve the existing head;
- future-row invariance and deterministic replay pass with deterministic clock injection;
- the shadow namespace is attached after active RegimeV2 evaluation;
- no Phase-F event sequencing, role reversal, MTF composition or policy consumption was added;
- `models.yaml` defaults the shadow producer to disabled;
- existing family tests remain green.

---

# Blast Radius

Expected remediation should remain limited to:

```text
src/libs/models/regime_v2/adapters/trendline_family_feature_producer.py
src/libs/models/regime_v2/adapters/__init__.py
src/apps/signal_app/pipeline/regime.py
tests/models/regime_v2/adapters/
```

A direct import adjustment in the existing active factory is allowed solely to restore optional import isolation.

No trendline-family model contracts, geometry, matching, lifecycle or interaction semantics need to change.

No probability, overlay rule, MoE, MTF, selection policy or execution implementation should change.

---

# Remediation Handoff

Apply Phase-E remediation only using:

- `plans/trendline-family-phase-e-review.md`
- `plans/trendline-family-phase-d-approval.md`
- `plans/trendline-family-codex-phase-execution-plan.md`
- `plans/trendline-family-model-architecture-plan.md`

Do not start Phase F.

Required work:

1. Restore strict optional import isolation.
   - Active `RegimeV2FeatureProducer` import/construction must not import or depend on the trendline-family shadow adapter when disabled.
   - Remove eager shadow imports from the shared adapters package or implement genuine lazy exports.
   - Import the shadow producer directly only inside the enabled shadow factory.
   - Add an import-failure isolation test.

2. Move the complete producer invocation under one fail-soft boundary.
   - Include family update, feature projection, latency capture and head-after inspection.
   - Unexpected post-save projection failures must return structured diagnostics rather than raise.
   - Report truthful repository head advancement.

3. Do not erase enabled construction failures.
   - Enabled malformed/unavailable shadow configuration must attach a deterministic invalid shadow payload.
   - Disabled mode must remain zero-work and must not load family YAML.

4. Make the pipeline defensive catch auditable.
   - Never silently omit the namespace for an enabled component failure.
   - Attach a stable outer-boundary unexpected-error payload.

5. Narrow expected exception handling.
   - Canonical family validation errors remain expected.
   - Generic programming errors must be logged and classified as `unexpected_error`.

6. Harden timestamp history ownership.
   - Require or explicitly fail when shadow-enabled bar appends lack a timestamp.

7. Strengthen decision-invariance tests.
   - Exercise the actual RegimeV2 trend overlay enabled.
   - Prove identical active gate/selection outputs with and without the shadow namespace.
   - Add the narrowest available MTF/MoE exclusion assertion without changing those stages.

Preserve all currently passing Phase-E repository, replay, future-row, typed-feature and artifact aggregation behavior.

Run:

```text
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/models/trendline_family \
  tests/models/regime_v2/adapters -q
```

Run the active RegimeV2, trendline adapter, selection and signal integration slice.

Run narrow Ruff and compileall on changed files.

Reindex codebase-memory, return the mandatory review package, and stop after Phase E.
