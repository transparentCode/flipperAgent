# Review → Architect: Phase-I Recommendation Ordering Failure

## Review Scope

Review of the stopped BTCUSDT 4h candidate/geometry v2 trial after canonical artifact verification rejected:

```text
persisted promotion recommendation does not match derived evidence
```

Reviewed evidence:

```text
plans/coder-to-review-trendline-family-candidate-real-data-trial-v2.md
artifacts/trendline_family_candidate_trials/
  btcusdt_4h_20250801_20251201_candidate_geometry_v2/
src/libs/models/trendline_family/optimization/evaluator.py
src/libs/models/trendline_family/optimization/artifacts.py
src/libs/models/trendline_family/optimization/contracts.py
src/libs/models/trendline_family/research_lab/artifacts.py
```

No files were modified during review.

## Findings by Severity

### Blocking — no-finalist recommendation identity depends on incoming trial order

The v2 bundle has no deterministic validation finalist. Both persisted and rederived recommendations correctly produce:

```text
decision: REJECT
rationale: no_validation_trial_passed_stage_owned_gates
finalist: None
```

A read-only independent probe found only two differing top-level fields:

```text
parameter_effect_audits
recommendation_id
```

The audit contents are identical as a set:

```text
same_audit_set = true
```

The persisted recommendation orders audits using the original grid-evaluation order:

```text
lookback 120/120/180/180/240/240
then quality 0.30/0.40 for each grid row
```

The verifier reloads primary trials ordered by `trial_id`, then calls the same recommendation builder. In the no-finalist branch, `build_promotion_recommendation()` flattens `validation_trials` in caller-provided order. `PromotionRecommendation.__post_init__()` sorts audits only by `parameter_name`, so ties preserve that caller order. The derived recommendation therefore has the same evidence in a different tie order, producing a different content-addressed `recommendation_id`.

Relevant paths:

```text
src/libs/models/trendline_family/optimization/evaluator.py
  build_promotion_recommendation(...)

src/libs/models/trendline_family/optimization/contracts.py
  PromotionRecommendation.__post_init__()

src/libs/models/trendline_family/optimization/artifacts.py
  VerifiedRunBundle._verify_derived_truth()

src/libs/models/trendline_family/research_lab/artifacts.py
  load_verified_phase_i_artifacts()
```

This is a deterministic ordering defect, not a data, metric, decision, holdout, or artifact-tampering finding.

## Blast Radius and Affected Flows

Affected:

```text
Phase-I runs with no validation finalist
promotion recommendation content identity
artifact self-verification
independent artifact reload
```

Not affected:

```text
market-data request or normalization
candidate evaluator results
fold or holdout boundaries
trial/result identities
parameter-effect audit contents
promotion decision semantics
runtime/config paths
RegimeV2, signal, selection, strategy, risk, execution, portfolio
```

Codebase-memory confirms `VerifiedRunBundle` is used by artifact writing and verification. `build_promotion_recommendation` remains offline Phase-I infrastructure with no production runtime caller.

## Validation Gaps or Confirmations

Confirmed:

```text
raw rows: 733 persisted and hash-bound
normalized rows: 732 confirmed and hash-bound
exact UTC boundaries: passed
same recommendation audit set: true
winner: None
only mismatched evidence field: audit ordering
```

The existing v2 artifact root must remain byte-identical during remediation. No new Binance request or Phase-I rerun is required to reproduce or validate the fix.

## Approval Status

**Request bounded canonical remediation.**

The v2 trial remains unverified until the ordering defect is fixed and the existing bundle passes independent read-only verification.

## Recommended Handoff

Implement only:

```text
plans/architect-to-coder-trendline-family-phase-i-recommendation-ordering-v1.md
```

Do not rerun the trial, open holdout separately, rewrite v2 artifacts, or begin tracker work.
