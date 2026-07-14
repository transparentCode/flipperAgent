# Trendline Family Research Lab — Final Remediation Re-review

## Review Scope

Independent final re-review of:

```text
research/trendline_family_research_lab.ipynb
src/libs/models/trendline_family/research_lab/
tests/models/trendline_family/research_lab/
```

The review replayed every prior blocker and additionally tested combined MTF/export behavior, non-smoke configuration provenance, cross-asset comparability under unequal parameter/sample policies, dead notebook controls, and sensitivity visualization completeness.

## Approval Status

**Request changes. The bounded candidate/geometry real-data research trial remains blocked.**

The remediation closes most prior findings, but four contract gaps remain. They are confined to the notebook/research support layer and do not affect runtime code.

---

## Resolved Findings

The following are independently verified as closed:

- default notebook executes top-to-bottom;
- nested immutable diagnostics serialize correctly;
- point-in-time position `0` renders the first snapshot;
- aware-UTC remote bounds reach the mocked Binance adapter with correct millisecond values;
- Binance timestamp-column normalization produces exact UTC indexes;
- local timestamps remain strict UTC;
- smoke/local source ambiguity rejects;
- local and remote modes require an explicitly supplied resolved config object;
- provider audit rows expose canonical `confirmed_bars`, `confirmed_pivots`, and `fitted_paths` metadata;
- replay-wide member and corridor histories exist;
- replay-derived export position/snapshot binding is implemented;
- canonical dataset-summary content participates in export identity and forged summaries reject;
- standalone MTF composition and exact projected-member figure execute;
- exact rails, projected corridors, timestamp-local zones, and event visibility remain distinct;
- verified Phase-I bundle browsing still exposes fold plan, completion index, freeze, holdout audits, holdout results, and recommendation;
- no runtime, YAML, RegimeV2, signal, selection, strategy, risk, execution, or promotion path changed.

Independent provider-audit evidence:

```text
rows:                         48
confirmed_pivot_count set:    41 rows
fitted_path_count set:        39 rows
final confirmed pivots:       16
final fitted paths:            2
```

Standalone MTF evidence:

```text
MTF snapshot created:          yes
projected members:             1
exact-member figure traces:    1
```

---

# Findings by Severity

## Blocking — Non-smoke research still accepts the deterministic smoke fixture configuration

Locations:

```text
src/libs/models/trendline_family/research_lab/replay.py
  validate_research_config(...)

research/trendline_family_research_lab.ipynb
  RESOLVED_CONFIG selection
```

The notebook now requires a caller-supplied resolved config when `SMOKE_MODE=False`, but `validate_research_config(...)` validates only type, asset, timeframe, and optional MTF enablement.

It still accepts:

```text
config_version: research_smoke_v1
field provenance: deterministic_smoke_fixture
```

Independent probe:

```text
validate_research_config(build_smoke_config(), ...)
accepted = true
```

The focused local and remote notebook tests also satisfy the non-smoke requirement by injecting `build_smoke_config(...)`. Therefore a real/local/remote research run can silently use the compact smoke thresholds while appearing to be a legitimate non-smoke run.

### Required correction

Add an explicit semantic configuration-purpose contract rather than relying on naming alone. Acceptable bounded options:

1. add a typed `ResearchConfigSpec` with purpose `SMOKE` or `RESEARCH`, bind it to the notebook/run context, and reject `SMOKE` in local/remote modes; or
2. add a fail-closed validator that rejects the known smoke config identity/provenance outside smoke mode.

Tests must prove:

```text
SMOKE_MODE=True + smoke config          -> accepted
local/remote + smoke config             -> rejected
local/remote + explicit research config -> accepted
```

Do not read or write runtime YAML.

---

## Blocking — MTF research and export are inconsistent when `MTF_RESOLVED_CONFIG` differs from the single-timeframe replay config

Locations:

```text
research/trendline_family_research_lab.ipynb
  MTF_RESOLVED_CONFIG
  compose_mtf_research(...)
  export cell

src/libs/models/trendline_family/research_lab/artifacts.py
  _validate_export_identity(...)
```

Standalone MTF mode now works with a separately supplied MTF-enabled config. However, the export context belongs to the single-timeframe replay config.

When smoke replay uses its disabled smoke config and MTF research uses the separate MTF-enabled config, enabling both:

```text
RUN_MTF_RESEARCH = True
EXPORT_ARTIFACTS = True
```

fails with:

```text
ContractValidationError:
MTF snapshot identity does not match research context
```

This contradicts the notebook surface, which explicitly permits `MTF_RESOLVED_CONFIG`, and the export requirement to include the composed MTF snapshot when MTF research ran.

### Required correction

Choose one explicit design and enforce it:

- **Single-config design:** require the main `RESOLVED_CONFIG` to be MTF-enabled and remove `MTF_RESOLVED_CONFIG`; or
- **Dual-context design:** introduce a typed MTF research context and bind both the single-timeframe replay identity and MTF policy identity into the export manifest.

The export validator must verify the selected design rather than comparing an MTF snapshot against an unrelated single-timeframe config hash.

Add a compact notebook test proving:

```text
MTF research + export -> succeeds
export manifest binds MTF snapshot ID and policy/config identity
serialized MTF snapshot is present
```

No refitting, averaging, timeframe dominance, or signal inference is permitted.

---

## Blocking — Cross-asset comparison is still fail-open for parameter and sample comparability

Location:

```text
research/trendline_family_research_lab.ipynb
  compare_replay_summaries(...)
```

The function now allows asset-specific resolved hashes, but its gate checks only:

```text
model_version
config_version
timeframe
provider_spec
```

`COMPARISON_POLICY` is a plain global dictionary displayed in output; it is not validated against the input replays and does not bind actual parameter or sample semantics.

Independent adversarial comparison used:

```text
BTCUSDT: 48 bars, candidate lookback 48
ETHUSDT: 32 bars, candidate lookback 24
same config_version string
same model version/timeframe/provider
```

Result:

```text
comparison accepted: true
eligible bars: [48, 32]
resolved config hashes differ: true
```

The comparison can therefore present structurally incomparable assets as one valid panel.

### Required correction

Move comparison semantics into the tested support package and introduce a typed, content-addressed comparison policy/audit binding:

- model version;
- parameter-policy hash excluding only allowed asset-specific identity fields;
- timeframe;
- provider specification;
- confirmed start/end window or explicitly normalized common window;
- eligible-row/sample definition;
- required coverage policy;
- metric definitions.

Required behavior:

```text
equivalent asset-specific configs + same sample policy -> accepted
different candidate/tracker/event parameters          -> rejected
unequal/unapproved date or row coverage                -> rejected or explicitly normalized
different timeframe/provider/sample definition        -> rejected
```

Report unambiguous unique-family and family-snapshot counts as currently implemented.

---

## Major — Sensitivity visualization and dead-control cleanup remain incomplete

Locations:

```text
research/trendline_family_research_lab.ipynb
  sections 1, 8, 9, 12, 13
```

The stage-specific sensitivity section still displays validation-only DataFrames. It does not create the required stage-specific Plotly chart or expose a typed metric selector.

The prior handoff required each declared control to drive one explicit reviewed action or be removed. These remain effectively dead or declarative only:

```text
SOURCE_TIMEFRAMES          occurrence count: 1
FOLD_PARAMETERS            occurrence count: 1
REPLAY_START_POSITION      occurrence count: 1
RUN_PHASE_I_EXPERIMENT     declaration/flag only
```

`CANDIDATE_OUTCOME_POLICY` and `INTERACTION_OUTCOME_POLICY` only produce an `UNAVAILABLE` message and do not execute an approved evaluator path.

### Required correction

1. Add a tested `build_parameter_sensitivity_figure(...)` support helper that:
   - accepts only validation rows;
   - rejects or omits holdout rows;
   - requires explicit stage and metric;
   - plots parameter value versus metric with fold/worst-window evidence;
   - never reranks from holdout.
2. Remove dead controls that are not part of this notebook release.
3. Keep `RUN_PHASE_I_EXPERIMENT` absent unless it performs one explicitly reviewed validation-only action. Artifact browsing alone does not require that flag.
4. Either remove candidate/interaction outcome-policy controls or wire them to a bounded validation-only Phase-I evaluator without opening holdout.

This item is major rather than runtime-critical, but it blocks notebook approval because it was an explicit required workflow and remediation condition.

---

## Blast Radius and Affected Flows

The remaining remediation must stay inside:

```text
research/trendline_family_research_lab.ipynb
src/libs/models/trendline_family/research_lab/
tests/models/trendline_family/research_lab/
```

No changes are expected in:

```text
canonical provider/tracker/matching/rails/corridors
interaction/event lifecycle
Phase-H MTF compositor semantics
Phase-I optimizer/evaluator/promotion semantics
RegimeV2 or adapters
signal/selection/strategy/risk/execution
configs/trendline_family.yaml
```

`run_phase_i_evaluation` has no inbound production callers. `run_canonical_replay` remains research-only; its indexed caller is the causality helper.

---

## Validation Confirmations

Independent suites:

```text
Research lab:                           17 passed
Trendline + adapters/projected runtime: 367 passed
Active RegimeV2/selection/signals:      148 passed
```

One existing OpenTelemetry `LoggingHandler` deprecation warning remains.

Static checks:

```text
Ruff:                  passed
compileall:            passed
notebook JSON:         valid, nbformat 4, 34 cells, outputs cleared
git diff --check:      passed
```

Codebase-memory:

```text
project: Users-aloobhujia-flipperAgent
nodes:   41,752
edges:   139,181
status:  ready
```

Independent remaining-failure probes:

```text
non-smoke validator + build_smoke_config:
  accepted (must reject)

MTF mode alone:
  passed

MTF mode + export with separate MTF config:
  ContractValidationError: MTF snapshot identity does not match research context

cross-asset comparison with different lookbacks and 48 vs 32 bars:
  accepted (must reject or explicitly normalize)

stage-specific sensitivity figure:
  absent
```

---

## Recommended Handoff

Apply only the four bounded corrections above, add adversarial tests for each, and rerun every compact notebook mode.

Stop before:

```text
real-market candidate/geometry trial
holdout opening
runtime config promotion
RegimeV2 work
oscillator trendlines
Phase J or live dashboards
```

The next review should be an approval gate, not another architecture expansion.
