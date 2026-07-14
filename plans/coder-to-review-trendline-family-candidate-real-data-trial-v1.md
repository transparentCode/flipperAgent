# Coder → Review: Trendline-Family Candidate/Geometry Real-Data Trial v1

## Scope Executed

Implemented only fixed-scope trial runner and mocked preflight coverage:

```text
scripts/run_trendline_family_candidate_geometry_trial.py
tests/scripts/test_trendline_family_candidate_geometry_trial.py
```

No canonical model, optimization, adapter, runtime, YAML, RegimeV2, signal,
selection, strategy, risk, execution, or portfolio file changed.

## Fixed Experiment Identity

```text
market:     Binance USD-M Futures
asset:      BTCUSDT
timeframe:  4h
start:      2025-08-01T00:00:00Z
end:        2025-12-01T00:00:00Z
limit:      1000
expected rows: 732
```

Resolved local baseline before remote execution:

```text
config version:       1
model version:        trendline_family_v1
resolved config hash: da15ebbcb42a9148714394b35d94e246c412af964c53024d43f221c30bd8a08f
candidate lookback:   180
candidate min bars:   40
fractal left/right:   3 / 3
minimum pivots:       2
minimum quality:      0.35
```

Baseline matches approved handoff. No YAML write occurred.

## Pre-Network Validation

Passed:

```text
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/scripts/test_trendline_family_candidate_geometry_trial.py -q
5 passed

PYTHONPATH=src .venv/bin/python -m pytest \
  tests/models/trendline_family/optimization/test_phase_i_remediation.py \
  tests/models/trendline_family/optimization/test_runner_and_artifacts.py -q
21 passed

ruff check scripts/run_trendline_family_candidate_geometry_trial.py \
  tests/scripts/test_trendline_family_candidate_geometry_trial.py
All checks passed

PYTHONPATH=src .venv/bin/python -m compileall -q \
  scripts/run_trendline_family_candidate_geometry_trial.py \
  tests/scripts/test_trendline_family_candidate_geometry_trial.py
Passed

git diff --check
Passed
```

Mock coverage proved fixed request parameters, exact 732-row preflight,
config drift rejection, fixed fold/grid/objective identity, fixed Phase-I call,
and no config YAML mutation.

## Remote Execution Result

**Stopped. No Phase-I evaluation, holdout opening, artifact verification, or
trial report occurred.**

One invocation of the fixed runner reached the single Binance request, then
failed before normalization and preflight while attempting to persist raw
request evidence:

```text
OSError: Cannot save file into a non-existent directory:
.../input
```

Cause: `persist_raw_fetch_evidence()` wrote `input/raw_binance_response.csv`
without first creating the `input/` directory.

The fixed root now contains only preserved execution-scope evidence:

```text
artifacts/trendline_family_candidate_trials/
  btcusdt_4h_20250801_20251201_candidate_geometry_v1/
    execution_scope.json
```

No raw response, normalized input, input manifest, fold plan, Phase-I artifact,
holdout audit, recommendation, or model metric was persisted. Therefore no
claim can be made about data validity or candidate quality.

## Stop Contract

The trial root is intentionally non-reusable. The runner rejects any rerun of
this exact root. No second request, alternative asset/timeframe/window, grid
change, or holdout workaround was attempted.

Do not treat this as a data failure or model result. It is a local runner
artifact-path failure after the one permitted remote invocation.

## Required Next Decision

Current handoff is exhausted. A new explicit approval is required before:

1. fixing the runner to create its raw-evidence parent directory and adding a
   regression test; and
2. authorizing any new remote request under a new trial identity.

The original bounded dataset was not persisted, so it cannot be preflighted or
evaluated without another remote request.

## Not Changed

- BinanceNativeAdapter or pagination behavior.
- `configs/trendline_family.yaml` and runtime configuration.
- Candidate/tracker/interaction/MTF model semantics.
- Phase-I objective, fold, grid, runner, holdout, or promotion semantics.
- RegimeV2 and all production execution paths.

## Risks

- One-request constraint prevented recovering the unpersisted remote response.
- This run provides no research evidence and must not be counted as a completed
  candidate/geometry trial.
