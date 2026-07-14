# Trendline Family Research Lab — Independent Review

## Current Mode

Independent architecture, causality, notebook-execution, and research-surface review after the first canonical research-lab implementation.

## Decision

**Revision required. The bounded candidate/geometry real-data research trial remains blocked.**

The implementation has the correct high-level package boundary:

- research support is isolated under `libs.models.trendline_family.research_lab`;
- runtime modules do not import the research package;
- no legacy trendline runtime is imported;
- no RegimeV2, signal, selection, strategy, risk, execution, YAML, or promotion path changed;
- canonical tracker/provider/repository, Phase-H MTF contracts, and Phase-I artifact verification are reused rather than reimplemented.

However, the committed notebook does not execute top-to-bottom in its default smoke mode, advertised opt-in modes are unreachable or placeholders, local/remote timestamp handling is causally unsafe, current chart rendering misstates timestamp-specific corridor/zone evidence, and research-export identity does not bind the actual selected output.

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

Also inspected the canonical Phase A–I APIs used by the support package and the existing Binance-native adapter contract.

---

## Verified Positive Boundaries

### Canonical implementation ownership

The research package calls the approved canonical tracker, provider, repository, immutable historical frame, MTF compositor, and Phase-I artifact verifier.

No duplicate fitting, matching, lifecycle, event, MTF relation/cluster, objective-gate, or promotion implementation was found.

### Runtime and Regime isolation

Verified:

```text
no runtime import of trendline_family.research_lab
no RegimeV2 import in research support or notebook
no active signal/selection consumption
no runtime YAML read/write
no external fetch inside model or Phase-I evaluator code
no promotion/config mutation
```

### Core replay causality

`run_canonical_replay(...)` updates one clean in-memory canonical tracker over confirmed prefixes.

The focused causality fixture confirms:

```text
snapshot at T from full replay
==
snapshot at T from an independently truncated replay
```

### Phase-I artifact browsing

`load_verified_phase_i_artifacts(...)` discovers the declared artifact files and calls `verify_artifact_bundle(...)` before returning a browser object.

A missing indexed trial file rejects.

### Static and regression quality

All reported Python suites, lint, compilation, notebook JSON, and diff checks pass. These checks do not execute the notebook cells and therefore do not expose the default execution failures below.

---

# Blocking Findings

## P0 — The committed default smoke notebook does not execute top-to-bottom

Locations:

```text
src/libs/models/trendline_family/research_lab/contracts.py:342-352
research/trendline_family_research_lab.ipynb cells 9 and 17
```

### Nested immutable diagnostics break `record_to_dict`

`record_to_dict(...)` calls:

```python
asdict(value)
```

`SnapshotSummary.diagnostics` contains nested immutable `mappingproxy` values from the canonical snapshot. `dataclasses.asdict(...)` attempts a deep copy and fails because `mappingproxy` cannot be pickled.

Independent default-cell execution failed in notebook cell 9:

```text
TypeError: cannot pickle 'mappingproxy' object
```

The notebook therefore stops before displaying the final canonical snapshot summary.

### Missing notebook import

After applying a non-persistent runtime shim only to continue review, notebook cell 17 failed:

```text
NameError: event_transition_rows is not defined
```

The function is called but not imported in the notebook configuration/import cell.

### Required correction

1. Replace `dataclasses.asdict(...)` with a recursive field-by-field dataclass adapter that does not deep-copy immutable mappings.
2. Preserve UTC datetime and enum conversion exactly.
3. Add `event_transition_rows` to the notebook import list.
4. Add a real notebook smoke-execution test that executes every code cell in order with network and writes disabled.
5. The test must fail on any cell exception, not only validate JSON/headings.
6. Do not commit generated outputs after the execution test.

---

## P0 — The top-level safety assertion makes every advertised opt-in mode unreachable

Location:

```text
research/trendline_family_research_lab.ipynb cell 2
```

The notebook contains:

```python
assert SMOKE_MODE and not any(
    (
        FETCH_REMOTE,
        RUN_POINT_IN_TIME_REPLAY,
        RUN_MTF_RESEARCH,
        RUN_PHASE_I_EXPERIMENT,
        RUN_MULTI_ASSET_COMPARISON,
        EXPORT_ARTIFACTS,
    )
)
```

Independent in-memory flag probes produced:

```text
local_mode  -> AssertionError
replay_mode -> AssertionError
export_mode -> AssertionError
mtf_mode    -> AssertionError
```

Consequences:

- local CSV/Parquet mode cannot be enabled;
- point-in-time replay cannot be enabled;
- export cannot be enabled;
- MTF research cannot be enabled;
- multi-asset mode cannot be enabled;
- the Phase-I experiment flag cannot be enabled.

The assertion proves the committed defaults rather than validating a selected runtime mode. It must not prevent explicit research actions.

### Required correction

Replace the global default assertion with typed mode validation, for example:

- reject `SMOKE_MODE` and `FETCH_REMOTE` simultaneously;
- reject remote fetch without explicit UTC bounds;
- reject local-path and remote modes when both are selected;
- leave replay/export/MTF display flags independently usable;
- keep holdout opening impossible in this notebook task;
- keep RegimeV2 absent.

Add tests that execute at least:

```text
default smoke mode
local-file mode
point-in-time renderer enabled
export enabled into tmp_path
```

Remote exchange calls must remain mocked or statically normalized in tests.

---

## P0 — Local and remote timestamp handling is causally unsafe

Locations:

```text
src/libs/models/trendline_family/research_lab/replay.py:204-214
research/trendline_family_research_lab.ipynb remote-fetch cell
src/apps/ingestion_app/adapters/binance_native.py
```

### Remote adapter output uses a timestamp column, not a timestamp index

The Binance-native adapter returns an adapter-shaped frame with:

```text
timestamp
open
high
low
close
volume
...
```

and a default range index.

The notebook currently executes:

```python
remote.index = pd.to_datetime(remote.index, utc=True)
```

This converts the integer range index to nanoseconds around the Unix epoch instead of using the exchange millisecond timestamp column.

Independent adapter-shaped probe produced:

```text
remote_notebook_index:
1970-01-01T00:00:00+00:00
1970-01-01T00:00:00+00:00

source timestamp column:
1704067200000
1704070800000
```

Nanosecond differences are also discarded when converted to Python datetimes, creating duplicate semantic observed times.

This path cannot be used for causal research.

### Local loader silently localizes naive timestamps

`load_local_ohlcv(...)` uses:

```python
pd.to_datetime(..., utc=True)
```

A CSV containing timezone-naive strings was silently accepted as UTC:

```text
naive_local_ACCEPTED_AS_UTC
```

The approved data contract requires explicit timezone-aware UTC input and rejection of semantic ambiguity, not silent localization.

### Required correction

1. Add one tested adapter-normalization helper in the research support package.
2. For Binance-native data:
   - require the `timestamp` column;
   - parse it explicitly with `unit="ms"` and `utc=True`;
   - set it as the index;
   - remove the source timestamp column after binding the index;
   - preserve strict ordering and uniqueness;
   - determine completeness from requested bounds/current close-time evidence rather than blindly relabeling arbitrary rows;
   - do not use the range index as market time.
3. For local files:
   - parse timestamps without silently forcing UTC first;
   - reject timezone-naive values;
   - accept only timezone-aware values with zero offset, or apply one explicitly documented conversion policy before canonical validation.
4. Add adversarial tests for:
   - naive local timestamp rejection;
   - non-UTC offset policy;
   - duplicate/unsorted timestamp rejection;
   - actual Binance-native frame shape;
   - millisecond conversion correctness;
   - no incomplete final bar entering the immutable frame.

No network call belongs in tests.

---

## P1 — Corridor and interaction-zone chart traces misstate their time semantics

Location:

```text
src/libs/models/trendline_family/research_lab/plotting.py:89-126
```

A `FamilyCorridor` is a structural envelope projected at its persisted snapshot timestamp. An `InteractionZone` is a confirmed-bar observation zone at one persisted observation timestamp.

The current renderer draws:

```python
y=[corridor.lower_price] * len(x_values)
y=[corridor.upper_price] * len(x_values)
```

and uses `add_hrect(...)`, which spans the complete x-domain for each timestamp-specific zone.

Independent smoke probe found a nonzero-slope singleton corridor:

```text
representative slope: 1.3888888888888757e-05
```

but its plotted corridor trace had:

```text
unique y values: 1
```

The exact rail was sloped while the same singleton corridor was rendered as a horizontal historical line. The zone similarly covered the complete chart domain even though it belongs to one confirmed timestamp.

This breaks the required distinction between exact geometry, structural corridor, and bar-scoped interaction evidence.

### Required correction

Choose one explicit display policy and persist it in chart-ready records:

1. **Snapshot projection view:** derive corridor bounds across x only from the exact member geometries present in that snapshot, selecting the exact lower/upper member value at every displayed timestamp; or
2. **Timestamp-local audit view:** render the persisted corridor and zone only at/around their actual snapshot/observation timestamp.

For interaction zones, prefer timestamp-local rectangles or bar-width segments.

Do not draw a current zone across historical bars.

Also:

- skip events outside the visible frame instead of adding NaN markers;
- include source timestamp/snapshot provenance in hover data;
- keep uncertainty in a distinct record/trace or explicitly display it as unavailable;
- add tests proving a sloped singleton corridor never becomes a horizontal chart trace across history.

---

## P1 — Research-run identity does not bind provider semantics or the selected export evidence

Locations:

```text
src/libs/models/trendline_family/research_lab/contracts.py:22-70
src/libs/models/trendline_family/research_lab/replay.py:130-192
src/libs/models/trendline_family/research_lab/artifacts.py:88-119
```

### Different provider semantics can share one research-run ID

`run_canonical_replay(...)` accepts a provider argument, but `ResearchRunContext` does not bind provider identity.

Independent probe:

```text
same dataset/config/research parameters
native provider candidate count: 76
forced-empty provider candidate count: 0
same research_run_id: true
same final snapshot: false
```

### Different selected snapshots overwrite the same research-run directory

`export_research_artifacts(...)` uses:

```python
root = output_root / context.research_run_id
```

but `context.research_run_id` does not include:

- selected snapshot ID;
- selected replay position/timestamp;
- table identities;
- optional MTF snapshot ID;
- referenced Phase-I artifact identities;
- provider semantic identity.

Independent probe exported snapshot 20 and then the final snapshot under the same context:

```text
same_research_run_path: true
snapshot_overwritten: true
```

The same semantic run directory can therefore contain different evidence depending on write order.

The notebook also passes the Phase-I manifest run ID into a file named `phase_i_artifact_ids.json`, which is not the same thing as binding the referenced artifact-envelope IDs.

### Required correction

1. Bind canonical provider/evaluator identity to the replay context. For custom providers, require an explicit immutable research provider spec rather than using class name alone.
2. Add a distinct content-addressed `ResearchExportManifest` or bundle identity binding:
   - research replay context ID;
   - selected snapshot ID and timestamp;
   - selected position;
   - deterministic table payload hashes;
   - optional MTF snapshot ID;
   - verified Phase-I run ID and exact referenced artifact IDs;
   - chart/export schema versions.
3. Write under the export-bundle ID, or reject an attempt to overwrite a different semantic payload at an existing path.
4. Validate selected snapshot asset/timeframe/model/config identity against the research context.
5. Validate MTF asset/decision-timeframe identity when supplied.
6. Add tests proving:
   - different providers produce different replay-context IDs;
   - different selected snapshots produce different export IDs/paths;
   - unrelated snapshots reject;
   - repeated equivalent export is byte-stable;
   - changed table evidence changes export identity;
   - Phase-I references come only from a successfully verified bundle.

---

## P1 — Several required notebook research sections are headings or raw tables, not implemented research workflows

Locations:

```text
research/trendline_family_research_lab.ipynb sections 5, 6, 7, 9, 10, 11, 12, 13, 14, and 15
```

### Declared but unused configuration

Independent occurrence scan found several controls only at declaration:

```text
SOURCE_TIMEFRAMES             used once
CANDIDATE_OUTCOME_POLICY      used once
INTERACTION_OUTCOME_POLICY    used once
FOLD_PARAMETERS               used once
REPLAY_START_POSITION         used once
RUN_PHASE_I_EXPERIMENT        declaration + global assertion only
RUN_MULTI_ASSET_COMPARISON    declaration + global assertion only
```

### Missing or incomplete workflows

- **Candidate/pivot diagnostics:** no typed pivot/status table from provider metadata and no optional candidate-outcome analysis.
- **Family lifecycle diagnostics:** only the final family/transition tables are displayed; no state history, confidence history, member continuation history, representative history, source-group audit table, or birth/dormancy/reactivation/expiry aggregation over replay.
- **Interaction/event diagnostics:** only final-snapshot rows are displayed rather than a replay timeline.
- **Longevity and structural outcomes:** section 9 is explanatory Markdown only.
- **MTF research:** setting the flag reaches an unconditional `RuntimeError`; no independently updated source replay or MTF figure is implemented.
- **Phase-I browser:** the support object exposes only manifest, baseline, primary trials, recommendation, and paths; the notebook does not present fold plan, completion index, finalist freeze, holdout-open audits, or holdout evidence.
- **Parameter sensitivity:** displays a raw validation-only DataFrame but no stage-specific plots or metric selection.
- **Multi-asset comparison:** section 13 is Markdown only.
- **Performance diagnostics:** no chart-construction time or export/artifact-size evidence.
- **Export:** notebook configuration is only partially represented in `research_parameters`; MTF and event-transition/candidate evidence are not included in the notebook export call.

### Required correction

Implement the smallest complete offline workflows rather than adding another large orchestration layer:

1. Add deterministic history-table helpers over `ResearchReplay` for family state, members, transitions, observations, events, event transitions, corridors, and source-group audits.
2. Add candidate provider-metadata/pivot rows and optional `CandidateOutcomePolicy` display through the approved Phase-I evaluator, without opening holdout.
3. Add typed longevity/structural outcome tables using canonical Phase-I policies or explicitly label unavailable metrics with reasons.
4. Make MTF mode accept explicit independently replayed source datasets/configs and compose one canonical snapshot. Do not fetch or average inside MTF support.
5. Add a common-timestamp MTF plot from projected exact members plus typed source/relation/cluster tables.
6. Expand the verified artifact browser return type to include the typed fold plan, completion index, freeze, audits, and holdout results after verification.
7. Add stage-specific sensitivity plotting over validation results only.
8. Implement an optional deterministic multi-asset comparison function over caller-supplied comparable replay summaries. Keep it disabled by default.
9. Bind all notebook configuration that affects semantic output to the research/export manifest.

No RegimeV2 work is permitted.

---

## Bounded Remediation Scope

Expected files:

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
tracker runtime
matching/rails/corridors runtime
interaction/event lifecycle runtime
MTF compositor runtime
Phase-I optimization semantics
RegimeV2 or its adapter
signal worker
SelectionLayer
strategy/risk/execution
configs/trendline_family.yaml
```

Do not add notebook dependencies solely for execution. A focused IPython-based or equivalent cell runner is sufficient if already installed.

---

## Mandatory Remediation Tests

Add tests proving:

1. Every default notebook code cell executes in order without error.
2. Nested immutable snapshot diagnostics serialize through `record_to_dict`.
3. `event_transition_rows` is imported and callable in the notebook.
4. Local-file mode is reachable with `SMOKE_MODE=False`.
5. Replay and export flags are independently reachable.
6. Naive local timestamps reject.
7. Binance-native millisecond timestamp columns become exact UTC indexes.
8. Range indexes are never interpreted as market timestamps.
9. Sloped singleton corridor rendering is not horizontal across history.
10. Interaction zones are timestamp-local rather than full-domain rectangles.
11. Events outside the visible frame are skipped or explicitly typed as excluded.
12. Provider semantic changes alter research replay identity.
13. Selected snapshot changes alter export identity/path.
14. Unrelated snapshot/context export rejects.
15. Equivalent repeated export is deterministic and non-destructive.
16. MTF flag can execute a compact synthetic multi-source fixture without refitting or averaging.
17. MTF plot uses exact projected members and preserves missing/stale source rows.
18. Lifecycle and event timeline tables use persisted IDs across replay.
19. Longevity section produces typed structural rows or typed unavailable reasons.
20. Phase-I artifact browser exposes verified freeze/audit/holdout evidence when present.
21. Sensitivity plotting consumes validation-only rows.
22. Multi-asset comparison rejects incompatible sample definitions.
23. Runtime modules still do not import research support.
24. RegimeV2 remains absent.
25. Runtime YAML remains byte-identical.

---

## Validation Evidence

Independent suites reproduced:

```text
Research lab:                           11 passed
Full trendline-family:                 333 passed
Family + adapters/projected runtime:   361 passed
Active RegimeV2/selection/signals:     148 passed, 1 existing warning
```

Static checks:

```text
Ruff:                  passed
compileall:            passed
notebook JSON:         valid, nbformat 4, 32 cells
git diff --check:      passed
```

Independent notebook execution:

```text
default cell execution: FAILED at cell 9
reason: TypeError, nested mappingproxy serialization

continued with runtime-only serialization shim:
FAILED at cell 17
reason: event_transition_rows not imported
```

Independent mode probes:

```text
local mode:  AssertionError
replay mode: AssertionError
export mode: AssertionError
MTF mode:    AssertionError
```

Independent data probe:

```text
Binance-shaped timestamp column ignored
range index converted to 1970 timestamps
naive local timestamps silently accepted as UTC
```

Independent identity probe:

```text
different provider outputs -> same research_run_id
different selected snapshots -> same export path and overwrite
```

Codebase-memory:

```text
project: Users-aloobhujia-flipperAgent
nodes:   41,649
edges:   138,719
status:  ready
```

`run_canonical_replay` has no inbound production callers; its only indexed caller is the research causality helper. Direct source inspection remains necessary because the canonical package is untracked and generic change detection underreports it.

---

## Approval Boundary

The research notebook/support layer is not approved yet.

Blocked until re-review:

```text
bounded candidate/geometry real-data trial
research conclusions from the notebook
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

Apply only this bounded research-lab remediation, rerun the independent notebook execution and regression gates, and stop before any real-market trial.
