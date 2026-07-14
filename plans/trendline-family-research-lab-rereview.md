# Trendline Family Research Lab — Remediation Re-review

## Current Mode

Independent re-review after the first research-lab remediation.

## Decision

**Revision required. The bounded candidate/geometry real-data research trial remains blocked.**

The remediation materially improves the notebook and closes the original default-path failures:

- the committed notebook now executes top-to-bottom in default smoke mode;
- nested immutable snapshot diagnostics serialize without `mappingproxy` failure;
- `event_transition_rows` is imported and callable;
- local-file, replay and export flags are reachable;
- local timestamps must be explicitly UTC;
- Binance millisecond timestamp normalization exists in the support package;
- exact rails, projected corridors and timestamp-local interaction zones are visually separated;
- provider semantics participate in replay identity;
- selected snapshot and table hashes participate in export identity;
- replay-wide family, transition, observation, event and event-transition tables exist;
- the verified Phase-I browser exposes fold plan, completion index, finalist freeze, holdout-open audits and holdout results;
- no runtime, YAML, RegimeV2, signal, selection, strategy, risk, execution or promotion path changed.

Independent review still found fail-open or non-executable paths in remote research, MTF research, export closure and several advertised diagnostics.

---

## Review Scope

Reviewed:

```text
research/trendline_family_research_lab.ipynb

src/libs/models/trendline_family/research_lab/__init__.py
src/libs/models/trendline_family/research_lab/contracts.py
src/libs/models/trendline_family/research_lab/replay.py
src/libs/models/trendline_family/research_lab/tables.py
src/libs/models/trendline_family/research_lab/plotting.py
src/libs/models/trendline_family/research_lab/artifacts.py

tests/models/trendline_family/research_lab/test_notebook_contract.py
tests/models/trendline_family/research_lab/test_replay_tables_plotting.py
tests/models/trendline_family/research_lab/test_artifacts_and_boundaries.py
```

Replayed the prior smoke, mode, timestamp, chart, provider-identity, export-identity and verified-artifact boundaries. Also executed previously untested remote, MTF, multi-asset, first-position replay and dataset-summary adversaries.

---

## Verified Closed Findings

### Default notebook execution

Every default code cell executes in order with network and exports disabled.

The previous failures are closed:

```text
mappingproxy serialization: closed
event_transition_rows import: closed
```

### Local timestamp validation and Binance normalization helper

`load_local_ohlcv(...)` rejects timezone-naive timestamps.

`normalize_binance_ohlcv(...)`:

- requires the adapter `timestamp` column;
- parses integer milliseconds with `unit="ms"` and `utc=True`;
- removes the source timestamp column;
- rejects unordered or duplicate timestamps;
- filters bars whose close is after the explicit UTC close bound;
- marks only the retained bars complete.

### Chart time semantics

The renderer now:

- projects exact member geometries across the displayed snapshot-projection view;
- derives corridor lower/upper values from the exact members at every displayed timestamp;
- renders interaction zones only around their persisted observation bar;
- skips events outside the visible frame.

A sloped singleton corridor no longer becomes a horizontal historical trace.

### Replay and export identity improvements

Custom providers require explicit semantic provider specifications.

Different provider specifications produce different replay-context IDs.

Different selected snapshots and changed table evidence produce different export bundle paths.

Unrelated asset/timeframe snapshots reject against the replay context.

### Verified Phase-I browser

An independently generated holdout-bearing fixture loaded through the browser with:

```text
finalist freeze:       present
holdout-open audits:   2
baseline holdout:      present
finalist holdout:      present
recommendation:        promote
```

The browser verifies the complete Phase-I bundle before returning typed evidence.

### Runtime isolation

Verified:

```text
no runtime import of trendline_family.research_lab
no RegimeV2 import or research use
no legacy trendline runtime import
no runtime YAML read/write
no active signal/selection change
no real-market trial
no automatic promotion
```

---

# Blocking Findings

## P0 — Notebook remote mode still fails before the Binance adapter call

Location:

```text
research/trendline_family_research_lab.ipynb remote-fetch cell
```

The mode validator correctly requires `START` and `END` to already be timezone-aware UTC. The remote cell then executes:

```python
pd.Timestamp(START, tz="UTC")
pd.Timestamp(END, tz="UTC")
```

Pandas rejects a timezone-aware value when `tz=` is supplied again:

```text
ValueError:
Cannot pass a datetime or Timestamp with tzinfo with the tz parameter.
```

Therefore every valid remote configuration fails before `get_historical_ohlcv(...)` runs.

The remote cell also always constructs:

```text
config_version = research_smoke_v1
field_provenance = deterministic_smoke_fixture
```

because `resolved_config = build_smoke_config(...)` is unconditional. Local and remote research consequently run with a configuration explicitly identified as a smoke fixture, with no supported caller-supplied resolved canonical config.

### Required correction

1. After `validate_research_mode(...)`, use `pd.Timestamp(START).timestamp()` and `pd.Timestamp(END).timestamp()` without adding another timezone.
2. Add an explicit `RESOLVED_CONFIG` or equivalent caller-supplied typed input.
3. Use `build_smoke_config(...)` only when `SMOKE_MODE=True`.
4. Require a caller-supplied `ResolvedTrendlineFamilyConfig` for local and remote research; validate asset/timeframe identity before replay.
5. Do not read or mutate runtime YAML.
6. Reject `SMOKE_MODE=True` together with a local data path instead of silently ignoring the local path.
7. Add an in-memory mocked Binance notebook execution test that reaches the adapter call and produces exact expected UTC timestamps.

---

## P0 — The export bundle does not bind or validate every exported payload

Locations:

```text
src/libs/models/trendline_family/research_lab/contracts.py
  ResearchExportManifest

src/libs/models/trendline_family/research_lab/artifacts.py
  export_research_artifacts
```

The export bundle ID binds:

- replay context ID;
- selected snapshot ID/timestamp;
- selected position as a caller-provided integer;
- table hashes;
- optional MTF snapshot ID;
- optional Phase-I hashes.

It does **not** bind or validate `dataset_summary`, even though that payload is exported under the bundle directory.

Independent probe exported the same context/snapshot/tables twice while changing only the dataset summary:

```text
first summary:
  dataset_hash = canonical dataset hash
  row_count    = 48

second summary:
  dataset_hash = forged
  row_count    = 999

same_export_dir = true
stored_summary  = forged payload
```

The second write overwrote semantic evidence inside a supposedly content-addressed bundle.

`selected_position` is also not cross-bound to the selected snapshot. A final snapshot was accepted with:

```text
selected_position = 0
selected_snapshot_timestamp = final dataset timestamp
```

Additionally, `PhaseIArtifactBrowser.verification_bundle_hash` is annotated as `str` but is populated with a mapping of per-path hashes.

### Required correction

Prefer an export API that receives `ResearchReplay` plus `selected_position`, derives the selected output itself, and cannot accept an unrelated position/snapshot pair.

The export manifest must bind at least:

- canonical dataset-summary payload hash;
- selected position derived against replay length;
- selected snapshot ID/timestamp derived from `replay.output_at(position)`;
- every table payload hash;
- optional MTF snapshot ID;
- verified Phase-I run ID and exact artifact hashes;
- export schema version.

Validate the dataset summary against the replay context:

```text
asset
timeframe
dataset_hash
row_count
UTC start/end
confirmed status
```

Reject or place in a different bundle any changed exported payload.

Correct the Phase-I verification hash type: either expose a typed mapping of artifact hashes or compute one deterministic aggregate hash.

---

## P1 — MTF notebook mode remains non-executable and has no geometry visualization

Locations:

```text
research/trendline_family_research_lab.ipynb configuration and MTF cells
src/libs/models/trendline_family/research_lab/plotting.py
```

The notebook always sets:

```python
resolved_config = build_smoke_config(...)
```

That configuration has:

```text
mtf.enabled = false
source_timeframes = ()
```

Supplying `MTF_SOURCE_SNAPSHOTS`, `MTF_NORMALIZATION_CONTEXT` and enabling `RUN_MTF_RESEARCH` therefore reaches the canonical compositor with an MTF-disabled config and rejects:

```text
ContractValidationError:
MTF composition requires mtf.enabled=True
```

There is no explicit MTF resolved-config input.

The MTF section now creates canonical typed tables, but still does not create the required common-decision-timestamp Plotly figure from exact projected members.

### Required correction

1. Add explicit `MTF_RESOLVED_CONFIG`, or require the caller-supplied resolved config to have MTF enabled and match the decision asset/timeframe.
2. Keep source snapshots caller-supplied and independently confirmed; do not fetch or refit inside the compositor path.
3. Add a compact synthetic notebook execution test with two source timeframes and one missing/stale source case.
4. Add an MTF figure that renders exact projected members at the common decision timestamp and preserves source timeframe/family/member provenance.
5. Do not average projected members, infer timeframe dominance or convert intersections into signals.
6. Pass the composed MTF snapshot into export when MTF research ran.

---

## P1 — Multi-asset comparison rejects normal cross-asset research

Location:

```text
research/trendline_family_research_lab.ipynb compare_replay_summaries
```

The comparison requires equality of:

```text
model_version
config_version
resolved_config_hash
```

Canonical resolved-config hashes bind asset identity. Two otherwise equivalent smoke configurations produced:

```text
BTCUSDT hash != ETHUSDT hash
```

An independent BTC/ETH comparison therefore rejected with:

```text
ValueError: multi-asset comparison requires matching model/config identity
```

The function also labels the total count of repeated replay family rows as `family_count`, rather than unique family count or a clearly named family-snapshot count.

### Required correction

Introduce a typed comparison policy/audit that separates:

- common model version;
- common parameter-policy identity;
- asset-specific resolved identity;
- timeframe;
- date window and confirmed-row coverage;
- provider specification;
- metric/sample definition.

Reject genuinely incomparable samples, but allow asset-specific resolved hashes when their parameter policy is declared comparable.

Report unambiguous counts such as:

```text
unique_family_count
family_snapshot_count
candidate_count
eligible_bar_count
```

Add a positive BTC/ETH comparison fixture and negative timeframe/sample-policy fixtures.

---

## P1 — Candidate provider audit fields are wired to metadata keys that do not exist

Locations:

```text
src/libs/models/trendline_family/research_lab/tables.py:103-114
src/libs/models/trendline_family/provider.py
```

`provider_audit_rows(...)` reads:

```text
pivot_status
pivot_count
fitting_status
```

The canonical provider emits fields such as:

```text
confirmed_bars
confirmed_pivots
fitted_paths
fit_metadata
reason_codes/status
```

Independent smoke replay result:

```text
rows:                    48
pivot_status non-null:   0
pivot_count non-null:    0
fitting_status non-null: 0
```

The final canonical result contained:

```text
confirmed_pivots = 16
fitted_paths      = 2
```

but the notebook displayed none of it.

### Required correction

Align the typed provider-audit contract with actual canonical metadata. Prefer explicit fields:

```text
confirmed_bar_count
confirmed_pivot_count
fitted_path_count
provider status
reason codes
fit status/reason where available
```

Do not fabricate unavailable values. Add tests against valid, insufficient-data, no-pivot and no-valid-path provider results.

---

## P1 — Remaining notebook controls and visual workflows are only partially wired

Locations:

```text
research/trendline_family_research_lab.ipynb
src/libs/models/trendline_family/research_lab/tables.py
```

### Replay position zero

The point-in-time cell uses:

```python
REPLAY_END_POSITION or dataset.row_count - 1
```

A requested position `0` is treated as false and renders the final bar instead.

Independent result:

```text
requested position: 0
rendered timestamp: final dataset timestamp
```

Use an explicit `is None` check and validate both replay start/end positions.

### Sensitivity visualization

The stage-specific sensitivity section still displays raw DataFrames only. It contains no Plotly sensitivity chart or explicit metric selector.

Add validation-only stage-specific plotting without holdout reranking.

### History completeness

Replay-wide families, transitions, observations and events exist, but member-rail and corridor histories are still final-snapshot-only in the notebook/export. Add deterministic replay-member and replay-corridor rows so representative/member continuation and corridor evolution can be inspected over time.

### Dead or ambiguous controls

Controls including `SOURCE_TIMEFRAMES`, `FOLD_PARAMETERS`, `RUN_PHASE_I_EXPERIMENT` and `REPLAY_START_POSITION` are declared but do not drive a complete workflow. Wire each control to one explicit reviewed action or remove it from the notebook surface.

`RUN_PHASE_I_EXPERIMENT` must not open holdout or run a real-market search in this task. The verified artifact browser may remain the only Phase-I notebook action.

---

## Bounded Remediation Scope

Expected files only:

```text
research/trendline_family_research_lab.ipynb

src/libs/models/trendline_family/research_lab/contracts.py
src/libs/models/trendline_family/research_lab/replay.py
src/libs/models/trendline_family/research_lab/tables.py
src/libs/models/trendline_family/research_lab/plotting.py
src/libs/models/trendline_family/research_lab/artifacts.py
src/libs/models/trendline_family/research_lab/__init__.py

tests/models/trendline_family/research_lab/
```

No changes are expected in:

```text
candidate provider runtime
tracker/matching/rails/corridors runtime
interaction/event lifecycle runtime
MTF compositor runtime
Phase-I optimization semantics
RegimeV2 or adapters
signal worker
SelectionLayer
strategy/risk/execution
configs/trendline_family.yaml
```

---

## Mandatory Remediation Tests

Add tests proving:

1. Default notebook still executes top-to-bottom.
2. Mocked remote notebook mode reaches the adapter with exact aware-UTC millisecond bounds and creates the expected UTC index.
3. Local and remote modes require an explicit non-smoke resolved config.
4. Smoke plus local-path ambiguity rejects.
5. Dataset-summary changes alter export identity or reject.
6. A forged dataset summary cannot overwrite an existing bundle.
7. Selected position and snapshot are derived from the same replay output.
8. Position zero renders the first snapshot, not the final snapshot.
9. MTF mode executes a compact MTF-enabled synthetic fixture.
10. The MTF figure contains one trace/marker per exact projected member and no synthetic average.
11. MTF export includes the composed snapshot identity.
12. BTC/ETH comparison succeeds under one explicit comparable policy despite asset-specific resolved hashes.
13. Incompatible timeframe or sample-policy comparisons reject.
14. Provider audit rows expose canonical `confirmed_pivots` and `fitted_paths` metadata.
15. Provider abstention reasons remain typed and visible.
16. Sensitivity plotting accepts validation-only rows and rejects/omits holdout rows.
17. Replay member/corridor histories preserve snapshot/family/member/corridor IDs.
18. Runtime modules still do not import research support.
19. RegimeV2 remains absent.
20. Runtime YAML remains byte-identical.

---

## Validation Evidence

Independent suites reproduced:

```text
Research lab:                           15 passed
Full trendline-family:                 337 passed
Family + adapters/projected runtime:   365 passed
Active RegimeV2/selection/signals:     148 passed, 1 existing warning
```

Static checks:

```text
Ruff:                  passed
compileall:            passed
notebook JSON:         valid, nbformat 4, 34 cells, outputs cleared
git diff --check:      passed
```

Independent positive probes:

```text
default notebook execution: passed
local + replay + export mode: passed
strict naive-local rejection: passed
Binance millisecond normalization helper: passed
sloped corridor projection: passed
timestamp-local zones: passed
provider identity separation: passed
selected-snapshot/table export separation: passed
verified Phase-I holdout browser: passed
```

Independent remaining-failure probes:

```text
aware UTC START/END + notebook remote conversion:
  ValueError before adapter call

notebook MTF config:
  mtf.enabled = false
  composition rejects

BTC/ETH comparison:
  rejects because asset-specific resolved hashes differ

provider audit metadata:
  all pivot/fitting fields None despite confirmed_pivots=16 and fitted_paths=2

dataset summary mutation:
  same export path accepted and overwritten

REPLAY_END_POSITION=0:
  final snapshot rendered
```

Codebase-memory:

```text
project: Users-aloobhujia-flipperAgent
nodes:   41,716
edges:   139,103
status:  ready
```

`run_phase_i_evaluation` has no inbound production callers. `run_canonical_replay` has no runtime callers; its indexed caller remains the research causality helper.

---

## Approval Boundary

The research notebook/support layer is not yet approved.

Blocked until re-review:

```text
bounded candidate/geometry real-data trial
research conclusions from local/remote notebook mode
MTF notebook research conclusions
Phase-I real-data artifact generation
any config patch review
any runtime promotion
```

Still explicitly excluded:

```text
RegimeV2 ablation or integration
oscillator trendlines
active signal/selection consumption
runtime configuration writes
Phase J or live dashboards
```

## Next Handoff

Apply only this bounded notebook/research-support remediation, rerun every notebook mode with compact synthetic or mocked evidence, and stop before any real-market trial.
