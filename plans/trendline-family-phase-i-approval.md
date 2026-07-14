# Trendline Family Model — Phase I Approval

## Current Mode

Final independent quant approval after Phase-I trust-boundary remediation.

## Approval Scope

Phase I offline optimization, evaluation, artifact, holdout, and promotion-review infrastructure for the canonical trendline-family model, including:

- immutable confirmed historical-frame validation and deterministic dataset identity;
- deterministic expanding/rolling walk-forward folds with warmup, purge, embargo, and untouched holdout;
- isolated candidate/geometry, tracker, and interaction evaluators;
- frozen candidate-stream and frozen family-snapshot boundaries;
- typed evaluator identities that fail closed for anonymous/custom callables;
- deterministic bounded grid enumeration and stage-ownership validation;
- content-addressed trial, result, fold, manifest, completion-index, and recommendation identities;
- one marginal counterfactual per tuned parameter;
- independently rederived parameter-effect and leakage audits;
- direction-aware objective gates and worst-window semantics;
- validation-only finalist selection followed by audited one-time holdout opening;
- persisted baseline parameter slices and exact expected primary trial request sets;
- complete artifact membership verification, including failed and invalid trials;
- independently rederived aggregate metrics, objective gates, finalist selection, audits, and final recommendation;
- review-only `PROMOTE`, `HOLD`, and `REJECT` recommendations;
- no runtime configuration mutation or active feature promotion.

RegimeV2 feature ablation remains implemented only as inactive offline infrastructure and is not approved for research execution while the regime module is WIP.

## Approval Decision

**Approved. Trendline-only real-data research may begin.**

Runtime/config promotion remains separately blocked pending evidence from bounded research trials and explicit human approval.

## Blocking Issues

None.

## Final Trust-Boundary Verification

### Evaluator semantics

Every semantic execution now requires either:

- a concrete evaluator-owned `StageEvaluationSpec`; or
- an explicit immutable `StageEvaluationSpec` supplied by the caller.

Validation and holdout execution require:

```text
supplied evaluator spec ID == trial evaluation spec ID
```

Holdout additionally requires:

```text
supplied evaluator spec ID == frozen finalist evaluator spec ID
```

A mismatch rejects before evaluator execution and before holdout-open registration.

### Complete deterministic trial request set

`RunManifest` now derives the exact expected primary trial IDs from:

- requested stage;
- asset/timeframe scope;
- deterministic search-space enumeration;
- dataset and fold-plan identities;
- baseline config hash;
- complete objective;
- evaluator specification;
- model/config versions;
- seed;
- every parameter override.

The persisted primary trial set must equal this exact request set. Failed and invalid expected trials remain mandatory.

Independent attack:

```text
manifest grid values: 180, 200
persisted trial values: one trial only
completion index and downstream IDs recomputed
```

Result:

```text
missing_grid_trial_REJECTED
completion primary trials do not match manifest expected request set
```

### Parameter-effect audit truth

For each tuned parameter, verification now independently rebuilds the required counterfactual:

```text
full trial overrides
with exactly one parameter reverted to persisted resolved baseline value
```

It verifies:

- exactly one audit per override;
- exactly one counterfactual per override;
- canonical baseline and trial values;
- exact single-parameter reversion;
- counterfactual trial/result identity;
- full and counterfactual stage-output fingerprints;
- full and counterfactual forbidden-output fingerprints;
- effect detection;
- leakage detection;
- changed-output claims;
- audit decision.

Independent attack changed an inert audit to claim an isolated effect and recomputed the parent result, recommendation, completion index, and manifest.

Result:

```text
forged_audit_REJECTED
parameter audit effect or leakage claim does not match evidence
```

### Finalist and holdout provenance

Persisted finalist freezes are cross-bound to:

- deterministic validation winner;
- stage;
- objective;
- fold-plan ID;
- evaluator specification;
- baseline and finalist validation results;
- manifest evaluator identity;
- baseline and finalist holdout trial specifications.

Independent attack replaced the frozen evaluator specification and recomputed the freeze, audits, manifest, completion index, and run identity.

Result:

```text
forged_freeze_REJECTED
finalist freeze evaluator does not match deterministic winner
```

### Derived recommendation truth

Bundle verification independently rebuilds:

- window aggregates;
- objective gates;
- comparable populations;
- validation finalist;
- parameter-effect audits;
- validation improvement;
- holdout confirmation;
- final recommendation.

A stored `PROMOTE` label is not authoritative. A fully reidentified promotion over worse holdout evidence rejects.

### Complete artifact closure

The completion index and verifier bind:

- run manifest;
- fold plan;
- baseline validation result;
- every primary trial;
- every counterfactual;
- every failed/invalid result;
- finalist freeze;
- both holdout-open audits;
- baseline and finalist holdout results;
- summary;
- recommendation;
- Markdown report.

Missing and unexpected artifact paths reject. Ordering does not affect semantic identity.

## Blast Radius Confirmation

Approved implementation remains inside:

```text
src/libs/models/trendline_family/optimization/
tests/models/trendline_family/optimization/
.codebase-memory index artifacts
```

Verified absent:

- runtime imports of the optimization package;
- reads or writes of `configs/trendline_family.yaml` from optimization code;
- external market-data fetching;
- legacy trendline runtime imports;
- active RegimeV2 consumption;
- SelectionLayer changes;
- signal-worker decision changes;
- strategy, risk, execution, or portfolio changes;
- runtime parameter hot reload;
- automatic config or feature promotion;
- real-data optimization runs during implementation/review.

`run_phase_i_evaluation` has no inbound production callers.

## Validation Sufficiency

Independent final validation:

```text
Phase-I optimization:                    29 passed
Full trendline-family:                  322 passed
Trendline + adapters/projected runtime: 350 passed
Active RegimeV2/selection/signals:      148 passed, 1 existing warning
```

The warning is the pre-existing OpenTelemetry `LoggingHandler` deprecation.

Static checks:

```text
Ruff:             passed
compileall:       passed
git diff --check: passed
```

Codebase-memory:

```text
project: Users-aloobhujia-flipperAgent
nodes:   41,522
edges:   137,692
status:  ready
```

Independent final attacks:

```text
forged parameter-effect audit: rejected
missing expected grid trial after full reidentification: rejected
forged finalist-freeze evaluator after full reidentification: rejected
```

## Residual Risk

Accepted residual risks:

1. No production-sized real-market optimization has run yet. The infrastructure is approved; model utility is not yet proven.
2. Candidate, tracker, and interaction objective definitions may require refinement after observing real-data distributions.
3. Operational timing from small fixtures is not evidence of production throughput.
4. Artifact hashes provide deterministic integrity and internal semantic consistency, not external cryptographic authorship or signing.
5. MTF policy-parameter search remains intentionally unimplemented.
6. RegimeV2 ablation and trendline-to-regime promotion remain blocked while RegimeV2 is WIP.
7. The research notebook has not yet been created.
8. The canonical package and approval files are untracked in the current broad dirty worktree and must be included deliberately in the eventual commit.

None of these risks blocks trendline-only offline research.

## Approved Next Handoff

Proceed in this order:

1. Build a thin canonical research notebook:

```text
research/trendline_family_research_lab.ipynb
```

The notebook must call canonical Phase A–I APIs and consume persisted artifacts. It must not reimplement candidate fitting, matching, lifecycle, event classification, MTF composition, objective gates, or promotion policy in cells.

2. Run one bounded candidate/geometry real-data trial on one liquid asset/timeframe using caller-supplied confirmed OHLCV.

3. Review validation distributions and parameter-effect evidence before opening holdout.

4. Open untouched holdout only for the frozen finalist under the approved audit path.

5. After candidate-stage review, run tracker research using one frozen candidate stream.

6. After tracker review, run interaction/event research using frozen canonical family snapshots.

7. Evaluate MTF structurally only after single-timeframe stages are stable.

8. Keep RegimeV2 ablation disabled and excluded from all research conclusions until the regime module receives separate approval.

9. Treat every `PROMOTE` result as a research recommendation only. Any runtime YAML edit or active feature consumption requires a separate approval decision.

## Final Status

```text
Phases A-H: approved
Phase I infrastructure: approved
Trendline-only real-data research: unblocked
Research notebook: not yet implemented
RegimeV2 ablation/use: blocked
Runtime/config promotion: blocked pending research evidence and human approval
```
