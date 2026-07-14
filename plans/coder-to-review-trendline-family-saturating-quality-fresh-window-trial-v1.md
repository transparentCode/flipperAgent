---
goal: Execute one immutable BTCUSDT 4h fresh-window saturating-quality research trial.
stage: coder-to-review
date_created: 2026-07-13
last_updated: 2026-07-13
owner: Codex
status: Blocked
tags: [handoff, quant, trendline-family, candidate, saturating-quality, fresh-window]
source_agent: Codex
target_agent: Quant Review
---

# Coder To Review: Saturating-Quality Fresh-Window Trial v1

## Status

**Blocked after the single authorized request.** The trial bundle fails its
mandatory independent input-identity verification. No retry was made or is
authorized under this handoff.

## Scope Executed

Created only:

- `scripts/run_trendline_family_saturating_quality_fresh_window_trial.py`
- `tests/scripts/test_trendline_family_saturating_quality_fresh_window_trial.py`
- `artifacts/trendline_family_saturating_quality_trials/btcusdt_4h_20251201_20260401_saturating_quality_v1/`
- this handoff
- generated `.codebase-memory/` index files

No canonical trendline-family package, YAML, runtime, tracker, MTF, RegimeV2,
signal, selection, or production application file was modified.

## Request And Input Evidence

The one authorized request was made exactly once through
`BinanceNativeAdapter.get_historical_ohlcv`:

```text
BTCUSDT / 4h
since: 1764547200000
until: 1775001600000
limit: 1000
```

Persisted raw response evidence:

```text
rows: 727
raw SHA-256: 9c94829cf0a98b08837090235b3f9010129f9c7131d54eac629034687bee71c8
```

The raw response normalized to the required 726 confirmed bars with the
required `2025-12-01T00:00:00Z` through `2026-03-31T20:00:00Z` boundaries.
The normalized CSV was atomically persisted with SHA-256:

```text
2be2f31fafef8188cf936326a43cbcc926ac4320a72658ed9977c403a98c1c42
```

The resolved canonical config hash was
`da15ebbcb42a9148714394b35d94e246c412af964c53024d43f221c30bd8a08f`.
The in-memory research-only override hash was
`448e25e2e5d8290ed99bfbc27a1117f3ddf169bd1c33675a6c07509b3c058e92`.

## Stop Condition

The persisted input manifest records this pre-persistence dataset identity:

```text
trendline-family-dataset_6e8da3e2931937132b3f56a24e2a6098ed51ccb5ee678cce3c49f81099b167b0
```

Read-only reload of `normalized_ohlcv.csv` produced:

```text
trendline-family-dataset_cfd9d4936b4bce5300c6858ef9a2ba387c27c7ccf5176655f6736bc26d6cb79a
```

The index, required OHLCV column dtypes, and displayed values matched. The
identity drift is caused by two auxiliary Binance decimal columns changing at
binary-float precision after CSV round trip:

- `volume`, `2026-01-09T20:00:00Z`: `9449.964` to `9449.964000000002`
- `volume`, `2026-01-29T04:00:00Z`: `9421.294` to `9421.294000000002`
- `taker_buy_base`, `2025-12-16T08:00:00Z`: `9459.08` to `9459.080000000002`
- `taker_buy_base`, `2026-03-07T04:00:00Z`: `9576.928` to `9576.928000000002`

`validate_trial_bundle(...)` therefore rejects with:

```text
FreshWindowTrialError: input manifest identity drift
```

This means the artifact bundle, persisted validation, freeze, holdout, report,
and decision are **not verified evidence**. They must not be used to make a
research, design, runtime, or trading conclusion.

## Bounded Artifact State

The runner did not check the reloaded dataset hash before beginning generation.
It consequently persisted the following unverified downstream evidence before
the final validator stopped:

- validation stream: 288 provider calls
- frozen validation finalist: `H=12`
- holdout stream: 96 provider calls
- total provider accounting: 384
- persisted program decision: `REJECT_HOLDOUT_GATE`

The decision is explicitly invalid for review because the input identity check
failed. No provider, evaluator, holdout, or network call was repeated after
the failure.

## Protected Sources

The `execution_scope.json` protected inventories canonically equal the live
source inventories after the attempt:

```text
v1 candidate trial: 1 file
v2 candidate trial: 30 files
approved report: 4 files
approved diagnosis: 4 files
approved density study: 4 files
approved quality study: 4 files
configs/trendline_family.yaml:
7a7fbc156a0ed3e01ac5b3d7502a76e834d6b34668daa8a569f32b4e63a887d8
```

No protected source byte changed.

## Validation Performed

Before the network request:

- focused runner suite: `14 passed`
- optimization and research-lab regression command: passed
- Ruff: passed
- compileall: passed
- `git diff --check`: passed
- codebase-memory module query: new runner module in-degree `0`; no production caller

After the request:

- focused runner suite: `14 passed`
- Ruff: passed
- compileall: passed
- `git diff --check`: passed
- independent bundle validation: **failed as above**
- codebase-memory status: `ready`, `47194` nodes, `149906` edges

## Required Follow-Up

Do not repair, regenerate, or rerun this root. A separate approved remediation
and fresh execution identity are required. That remediation must at minimum:

1. define a lossless normalized-input persistence representation or a canonical
   normalization schema that makes the persisted dataset hash reproducible;
2. verify persisted normalized dataset identity immediately after reload and
   before any provider call;
3. add a regression fixture containing auxiliary decimal Binance columns such
   as `volume` and `taker_buy_base`;
4. use a new trial identity and receive explicit one-request retry approval.

## Not Changed

No YAML/runtime mutation, no canonical quality implementation, no tracker work,
no RegimeV2 work, no network retry, no pagination, no fallback, no alternate
window, and no PnL or runtime claim was made.

