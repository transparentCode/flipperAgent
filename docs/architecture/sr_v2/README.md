# SR v2 architecture

## Review status

**IMPLEMENTED BASE / RESEARCH ONLY**
**Architecture record — no deployment or promotion claim**

These diagrams document the implemented clean-room structural research core and
its bounded offline/live facades. They do not authorize a model redesign,
scientific promotion, or production integration. Scientific status remains
`INCONCLUSIVE`; promotion status remains `RESEARCH_ONLY / NO_PROMOTION`.

Evidence labels are intentional:

- `[EXISTING]` — present in the implementation;
- `[RESEARCH-ONLY · EXISTING]` — present only in research/replay or read-only
  inspection;
- `[EXISTING GAP]` — a known boundary or missing capability;
- `[DEFERRED · NOT PRESENT]` — outside this implementation.

## Canonical and derived artifacts

D2 is canonical. SVGs are rendered from D2. Archify JSON and HTML are derived
static review views and must not become a second architecture source.

| View | Canonical D2 | Rendered SVG | Derived Archify | Visual receipt |
| --- | --- | --- | --- | --- |
| HLD | [overview.d2](overview.d2) | [overview.svg](overview.svg) | [JSON](interactive/overview.architecture.json) · [HTML](interactive/overview.html) | [receipt](interactive/overview.visual-check.json) |
| Structural LLD | [lld.d2](lld.d2) | [lld.svg](lld.svg) | [JSON](interactive/lld.architecture.json) · [HTML](interactive/lld.html) | [receipt](interactive/lld.visual-check.json) |
| Causal data flow | [causal-dataflow.d2](causal-dataflow.d2) | [causal-dataflow.svg](causal-dataflow.svg) | [JSON](interactive/causal-dataflow.dataflow.json) · [HTML](interactive/causal-dataflow.html) | [receipt](interactive/causal-dataflow.visual-check.json) |

Automated visual receipts carry `visualReview: pending` by contract. They are
bounded desktop evidence, not visual approval.

## HLD boundary

Resolved model, trial, and notebook YAML remain the configuration authorities.
YAML supplies runtime hyperparameters and research policy; code owns schema,
closed-bar/PIT, identity, and resource safety bounds.

Authenticated source data flows through
`BinanceUSDMResearchLoader` → `SourceBarRecord` →
`ResearchSourceSetManifest` for research replay. `SRV2ResearchReplay.run`
wraps the one `OfflineCompute` window/step loop. Both offline and live callers
send closed, sparse source windows into the stateless `SRModel.step` API using a
mandatory `SRState`.

Offline callers carry the returned immutable state. `LiveRuntime` derives its
closed trigger cutoff, submits a canonical state to the injected
`CheckpointRepository`, and exposes structural output only for an
`INSERTED`/`UPDATED` CAS winner. `TimescaleCheckpointRepository` stores only the
latest canonical state row in regular PostgreSQL table `sr_v2.checkpoints`.

The read-only viewer consumes bounded `SRV2ResearchTrace` projections. Decision
consumers remain disconnected.

## Scientific foundation boundary

`SRV2ResearchReplay.run` invokes the scientific callback only for closed trigger
cutoffs at or after `analysis_start`; its internal collector still reconstructs
the warm-up interval first. `ScientificObservationCompiler` consumes only
`CREATED` transitions, verifies the exact resolved ladder and source identity,
and retains observations after structural tombstone pruning.

`EpisodeEvidenceCollector` composes the same offline replay callback while
retaining only bounded counters, semantic hashes, state peaks, and compact
issuance indexes. Authenticated evidence is sealed as a content-addressed
`manifest.json` plus `episodes.jsonl`; `load_episode_artifact` verifies those
bytes for restart-safe reuse. Indexed target materialization labels one typed
tuple at a time over shared native bars and one common risk set, so tuple
choice cannot change structural identity or retain the full panel. The
authenticated `prepare_authenticated_target_plan` boundary verifies the exact
source slice and emits lazy `TargetOutcomeRow` streams with one
`TargetCompilerReceipt` per asset and target choice; `TargetDiagnosticAccumulator`
retains only fixed asset/timeframe/kernel/side counters, rolling digests, and
current-cutoff cluster state.

Each issuance receives a candidate-independent `simple_true_range_mean@1`
receipt over an exact causal native `N+1` suffix. `ResolvedTargetSpec` projects
the resulting symmetric first-passage label onto the continuous 15m trigger
grid. `feasible_random_price@3` selects a deterministic same-side opportunity
from the exact causal kernel window, preserves the stored left/right zone
offsets, and records an explicit unavailable result when overlap exclusion
leaves no center.

Development evaluation is calibration-free and research-only. It requires the
exact typed asset/timeframe/kernel ontology, excludes censored or ambiguous
reaction rows, and uses one joint UTC calendar-block resampling draw across
assets. Its only outcomes are `INVALID`, `INSUFFICIENT`, and `INCONCLUSIVE`;
there is no promotion, runtime probability, or protected-data path.

Package 2A adds a strict development-only optimizer contract under
`research/optimizer.py`. It resolves all source, split, target-identification,
finite global-parameter, inference, and resource choices without defaults. The
first feasible target tuple is selected in declared order; a sealed candidate
family is materialized before any evidence is evaluated; and geometry ranking
uses equal cutoff and asset weighting within exact timeframe/kernel/side
macros, with worst-macro-first tie breaking. Results remain
research statuses with at most a provisional development winner.

`research/preflight.py` receives authenticated native source-set manifests and
an injected single-asset evaluator. One asset and its complete native ladder
are pinned to each process, the frozen comparator runs twice, and atomic
append-only receipts retain source/model/target/compiler/family identities,
state bounds, completeness, and resource measurements. The versioned
`sr_v2.native_panel_preflight_receipt@2` also binds the authenticated source
slice, EpisodeArtifact@2 identity and measured artifact bytes, and requires a
zero provider-call count. Semantic hashes exclude wall-clock, RSS, and artifact
byte measurements, while source/artifact identities and structural state peaks
remain semantic. Receipt resume fails closed on identity, schema, or shape
changes. No provider call or real optimizer value is made by this package.

The strict development boundary is split into
`sr_v2.development_target_design@1` and
`sr_v2.development_global_geometry@1`. The target freeze authenticates the
first YAML-ordered feasible tuple, exact asset bindings, and code-derived target
fingerprints. Global geometry seals the complete finite family before evidence
evaluation; geometry evidence uses equal cutoff/cell weighting and one shared
UTC block draw receipt across assets. These APIs remain research-only and do
not select real policy values, open untouched validation, or promote a model.

## Structural LLD boundary

`SRStepRequest` contains lane identity, a closed `market_as_of`, exact sparse
source windows, and mandatory predecessor `SRState`. The model validates UTC
grid/cutoff alignment, per-bar and aggregate source fingerprints (schema-v4),
then evaluates the ordered YAML-selected `KERNEL_CATALOG` through `KernelSpec`
with exact suffixes. Lifecycle transitions and candidate replacement are
assembled under code-owned active/tombstone and kernel output bounds into
`SRStepResult`.

`SRStepResult.state` is the immutable next `SRState`. `GENESIS_EXACT` is an
explicit facade operation requiring sufficient windows; `CHECKPOINT_EXACT`
continues a compatible caller checkpoint. `WINDOW_RELATIVE` is research-only
and is not an exportable live checkpoint. State encoding is optional caller
checkpoint handling; it is not result encoding or implicit persistence.

## Causal data-flow boundary

Every structural step is closed-bar point-in-time: source bars close on or
before the selected cutoff; trigger progression is exact; higher-timeframe
windows are independent and supplied only when their expected source cutoff
advances; kernels never receive future source bars. The next state is published
only after the complete deterministic step. Research trace evidence and viewer
inspection remain cutoff-local and read-only.

## Explicit exclusions

The core, live runtime, and checkpoint output do not contain probability or
calibration fields, and there is no authenticated production
calibrator/predictor/optimizer or promotion path. Existing research-only
scoring scaffolding remains gated and non-promoted. Same-timeframe semantic
consolidation, cross-sectional features, MTF top-down selection or fusion,
intrabar processing, Decision/consumer integration, forecast, production
deployment/persistence claims beyond this research-only state boundary, and a
production aggregation/cache layer remain excluded. These are textual
exclusions, not reserved runtime components.

## One-year derived-fixture evidence

The bounded performance receipt is in
[one-year-performance.md](one-year-performance.md). It uses the authenticated
BTCUSDT 15m cache and causally aggregates complete UTC-aligned bars for the
configured higher timeframes solely inside the ad-hoc validation command. The
derived higher-timeframe bars are not independently authenticated source lanes,
and the run is not scientific efficacy or cache-speed evidence.
