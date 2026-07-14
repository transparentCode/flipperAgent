# Approval Decision: Trendline-Family Candidate/Geometry Real-Data Trial Retry v1

## Approval Scope

This approval covers only:

1. correcting the local input-artifact persistence defect in
   `scripts/run_trendline_family_candidate_geometry_trial.py`;
2. adding focused regression coverage for the corrected pre-request and
   persistence path; and
3. making exactly one new Binance USD-M Futures historical-kline request under
   a new immutable execution-attempt identity.

The approved research semantics remain unchanged:

```text
asset:      BTCUSDT
market:     Binance USD-M Futures
timeframe:  4h
start:      2025-08-01T00:00:00Z
end:        2025-12-01T00:00:00Z
limit:      1000
expected confirmed rows: 732
```

The original execution root is exhausted and immutable:

```text
artifacts/trendline_family_candidate_trials/
  btcusdt_4h_20250801_20251201_candidate_geometry_v1/
```

It contains only `execution_scope.json` and must not be reused, deleted,
rewritten, or interpreted as a data/model result.

## Blocking Issues

No blocker prevents a narrowly corrected second execution attempt.

The first attempt failed after its single authorized adapter call because
`persist_raw_fetch_evidence()` wrote to `input/raw_binance_response.csv`
without ensuring that `input/` existed. The failure occurred before
normalization, fold construction, Phase-I execution, holdout opening, artifact
verification, metric production, or recommendation.

The missing regression is itself part of the approved remediation and must pass
before the new remote request is made.

## Blast Radius Confirmation

Approved changes are limited to:

```text
scripts/run_trendline_family_candidate_geometry_trial.py
tests/scripts/test_trendline_family_candidate_geometry_trial.py
artifacts/trendline_family_candidate_trials/
plans/coder-to-review-trendline-family-candidate-real-data-trial-v2.md
.codebase-memory/
```

The implementation must not modify:

- `BinanceNativeAdapter` or pagination behavior;
- `configs/trendline_family.yaml`;
- canonical candidate, tracker, interaction/event, or MTF semantics;
- Phase-I optimization, holdout, audit, artifact, or recommendation semantics;
- RegimeV2 or its adapters;
- signal, selection, strategy, risk, execution, portfolio, or runtime paths.

Codebase tracing confirms that the affected persistence helpers are local to the
fixed research runner and are called only through `run_trial()` / `main()`.

## Validation Sufficiency

The stopped v1 implementation currently passes:

```text
focused runner tests: 5 passed
Ruff:                passed
compileall:          passed
git diff --check:    passed
```

These checks confirm the fixed experiment contract but do not cover the failed
parent-directory path. Before the new request, Codex must add and pass tests
that prove:

1. the new execution root and `input/` directory exist before the adapter is
   called;
2. raw response CSV and its manifest are persisted atomically under a fresh
   root;
3. the raw-response SHA-256 in the manifest matches the exact persisted bytes;
4. normalized input persistence also succeeds under the fresh root;
5. a mocked top-to-bottom runner reaches the post-persistence boundary with
   exactly one adapter call;
6. v1 root reuse remains rejected and v1 evidence remains unchanged;
7. the v2 identity and retry authorization fields are present in execution and
   input evidence.

All pre-network validation commands in the v2 architect-to-coder handoff are
mandatory.

## Residual Risk

Accepted risks:

1. Binance may return a dataset that fails the exact 732-row, timestamp, gap,
   completeness, or OHLCV preflight. That is a valid stopped result, not grounds
   for another request.
2. A later local or Phase-I failure could consume the one newly authorized
   request. No automatic retry is authorized.
3. The current adapter still performs one historical-kline request and is not
   suitable for multi-year windows without a separately reviewed pagination
   task.
4. One BTCUSDT 4h window can provide bounded structural evidence only; it cannot
   establish general model utility, runtime readiness, or profitability.

## Approval Decision

**Conditionally approved: Codex may apply the bounded persistence fix and, only
after all prescribed pre-network tests pass, make exactly one new request under
the v2 execution identity.**

The authorization is consumed when the adapter request is invoked, regardless
of whether later persistence, preflight, Phase-I evaluation, or verification
succeeds.

The Phase-I experiment semantics must remain identical to v1. In particular,
do not change the outcome-policy version, objective version, grid, folds,
holdout policy, seed, asset, timeframe, or date range merely to create the new
execution identity.

## Required Handoff

Codex must execute:

```text
plans/architect-to-coder-trendline-family-candidate-real-data-trial-v2.md
```

and return:

```text
plans/coder-to-review-trendline-family-candidate-real-data-trial-v2.md
```

No tracker trial, runtime promotion, config mutation, RegimeV2 work, Binance
pagination, or additional request is authorized.
