---
goal: Implement one minimal causal displacement-origin detector and decide whether it beats a matched naive zone on frozen TAOUSDT 1d development data.
stage: architect-to-coder
date_created: 2026-07-18
last_updated: 2026-07-18
owner: quant-orchestrator
status: Pending Approval
tags: [quant, sr, v2, displacement-origin, adequacy, kiss]
source_base: 4dd1f74d22dc0296c3d09599ef75906a7d0f147a
target_agent: Codex quant-coder
supersedes: plans/architect-to-coder-sr-v2.0-displacement-origin-adequacy-v1.md
---

# SR-V2.0 — Lean Displacement-Origin Adequacy

## Objective

Test one claim and stop at its decision gate:

> The price range immediately preceding a strong close through recent structure
> produces better first-revisit reaction quality than a deterministic matched
> naive zone.

V2.0 is a detector-adequacy experiment. It does not integrate the detector into
SREngine, change production configuration, optimize parameters, or open
holdout.

One approval covers implementation, tests, one frozen-data evaluation,
deterministic rerun, and coder-to-review handoff.

## Why This Replaces V1

The previous plan was too broad. This revision:

- does not carry legacy order-block defaults into V2;
- does not add a detector registry before a second detector exists;
- does not modify the V1 engine/configuration surface;
- does not duplicate artifact, control, fold, metric, or viewer infrastructure;
- does not make browser work part of hypothesis validation;
- runs one baseline only and returns one disposition.

## Branch and Boundaries

- Branch feature/sr-v2.0-displacement-origin-adequacy from clean main commit
  4dd1f74d22dc0296c3d09599ef75906a7d0f147a.
- Active package: src/libs/models/sr only.
- Legacy src/libs/sr is read-only reference. No imports, adapters, copied
  classes, configuration fallback, edits, or runtime dependency.
- Preserve all V1 behavior, public identities, config hashes, import boundaries,
  frozen evidence, and the zero-cycle architecture.

## Locked Hypothesis

### Data

- TAOUSDT, Binance USD-M, 1d.
- Reuse the verified frozen 629-bar development source bundle
  6b5a0a81117ba299516fb67ca2da81b3cb6e6f35ed6a85986a27689205a565d9.
- Point-in-time Wilder ATR(14), SMA seed, common start 28.
- No provider call, source refresh, contaminated 811-bar source, or holdout.

### Minimal detector

Create a pure closed-bar detector with four price-structure parameters:

- displacement_atr: 1.0
- minimum_body_fraction: 0.60
- structure_lookback_bars: 5
- base_search_bars: 3

These are a new simple V2 baseline, not migrated legacy values. Store them in a
strict typed V2 trial YAML. No hidden Python numeric defaults.

For confirmation bar t:

1. Use ATR known at t-1 as the displacement scale.
2. Require non-zero bar range.
3. Require abs(close-open) >= 1.0 * ATR[t-1].
4. Require abs(close-open)/(high-low) >= 0.60.
5. Bullish: close strictly exceeds every high in the prior five completed bars.
6. Bearish: close strictly falls below every low in the prior five bars.
7. Search the prior three bars nearest-first for an opposing candle. Doji is
   neutral and cannot be the base.
8. If no base exists, emit nothing.
9. Freeze the base candle full high-low range as the rectangular zone.
10. Bullish creates SUPPORT; bearish creates RESISTANCE.
11. formed_at = base close; available_at = confirmation close.
12. atr_at_creation = point-in-time ATR at confirmation close.
13. source = displacement_origin_v2.
14. Emit no more than one candidate per confirmation bar.

No future bars, later ATR, centered calculation, full-window normalization,
backfill, repainting, or intrabar availability.

### Outcome

Evaluate the raw immutable candidate zone, deliberately excluding lifecycle and
association:

- first touch begins at available_at plus one bar;
- inclusive OHLC/band intersection;
- touch search expires after 50 bars or fold end;
- reaction horizon is 10 bars, entirely inside the same fold;
- quality = favorable excursion ATR - adverse excursion ATR;
- incomplete/warm-up/invalid/censored cases are explicitly accounted.

This result answers only whether the detector has basic contextual utility.
Runtime interaction is a later gate.

### Null and folds

Reuse existing neutral V1.9 services rather than copying study logic:

- same six quarterly development folds from 2024_q3 through 2025_q4;
- two deterministic controls per eligible real touch;
- controls matched by fold, side, anchor time, ATR, and zone width;
- same first-touch, horizon, censoring, and reason precedence.

A new study may import neutral research services. It must not import another
canonical study or a historical scripts facade.

### Gates

Readiness must pass first:

- completed real outcomes >= 24;
- comparable folds >= 4;
- real outcomes per comparable fold >= 4;
- controls per side per comparable fold >= 4.

Utility:

- pooled median excess quality >= 0.10 ATR;
- positive-fold fraction >= 0.60;
- worst-fold excess >= -0.10 ATR.

Allowed dispositions:

- DISPLACEMENT_ORIGIN_BEATS_NAIVE_NULL
- DISPLACEMENT_ORIGIN_NOT_BETTER_THAN_NAIVE_NULL
- INSUFFICIENT_EVIDENCE

No fallback parameter set is allowed after seeing results.

## Minimal Architecture

Add only:

- a cohesive typed config module for displacement-origin detection;
- detection/displacement_origin.py using existing CandidateLevel,
  ZoneGeometry, ClosedBar, ZoneSide, and identities;
- one thin canonical research study under
  research/studies/displacement_origin_adequacy/;
- one strict V2 trial YAML;
- focused tests and a coder-to-review handoff.

Reuse:

- research source/frozen readers;
- Wilder ATR replay;
- fold contracts;
- first-touch metrics;
- baseline-adequacy neutral controls/metrics;
- artifact canonical JSON, manifest, publication, validation, and provenance.

Do not add:

- a registry, plugin loader, abstract kernel hierarchy, general ensemble API, or
  new database;
- a new artifact framework;
- a new viewer or JavaScript changes.

The evidence bundle only needs manifest.json, study.json, and cases.json.
cases.json must contain enough candidate/control/outcome records for semantic
recomputation and later visualization. Existing shared path-safety tests remain
authoritative; add only study-specific artifact/tamper regressions.

## Implementation Sequence

Use one branch and three logical commits:

1. Detector/config/tests.
2. Thin adequacy study, evidence validator, CLI, and tests.
3. Coder-to-review handoff with exact evidence and validation.

During development run focused tests. At final HEAD run the full validation
matrix once. Evaluate twice from the same implementation commit and require
byte-identical evidence.

## Required Validation

Focused:

- bullish and bearish creation;
- each detector condition independently failing;
- nearest opposing base at distances one through three;
- doji, tie, invalid ATR, zero-width, non-finite, ordering, duplicate and mixed
  state-key rejection;
- exact geometry, formation, availability, source, and identity;
- prefix causality and prefix/full replay parity;
- strict YAML missing/unknown/duplicate/type/range rejection;
- first-touch offset, 50-bar expiry, folds, censoring, control matching;
- gate precedence and all three dispositions;
- semantic validator rejects modified cases, metrics, identity, or disposition.

Final:

- two evaluation bundles byte-identical;
- focused V2 tests pass;
- full tests/models/sr suite passes;
- plain architecture suite passes;
- Ruff, compile/import, and git diff checks pass;
- V1 resolved values/provenance/hashes unchanged;
- V1.12 semantic validation and protected hashes remain exact;
- no generated evidence committed;
- worktree contains no unrelated changes.

Do not duplicate the full shared artifact path-safety regression matrix inside
the new study. The existing full SR suite already covers it.

## Diagnostics, Not Gates

Report without selecting or tuning on:

- candidate count by side/fold;
- detector rejection reasons;
- base distance;
- zone width in ATR;
- touch and censoring rates;
- nearby/overlapping candidate rate;
- favorable/adverse/quality distributions.

No visual approval is required in V2.0. If the hypothesis passes, V2.1 will
integrate engine semantics and reuse the existing all-zones viewer.

## Non-Goals

No SREngine/configs/sr.yaml/V1 pivot change; lifecycle, fakeout, reinforcement,
association, capacity, ZigZag, fractal, FVG, liquidity sweep, volume POC, TPO,
VWAP, trendline, multi-timeframe, regime, indicator, order flow, ML, ensemble,
confluence, parameter grid, per-asset tuning, provider/network/database,
holdout, viewer work, legacy edit, evidence commit, merge, deployment, or
trading decision.

## Decision Routing

- BEATS_NAIVE_NULL: plan V2.1 engine integration, all-zones visualization, and
  one small locked sensitivity study. Holdout remains closed.
- NOT_BETTER: close displacement-origin V2 without rescue tuning; select the
  next simple hypothesis family separately.
- INSUFFICIENT: report whether sparsity came from detection, touch, or censoring.
  Do not loosen rules or fetch data inside this branch.

No V2.0 outcome authorizes production use.
