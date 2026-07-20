---
goal: Test the SR-V2 displacement-origin price-structure hypothesis against a matched naive null using one causal, price-only detector and the frozen TAOUSDT 1d development source.
stage: architect-to-coder
date_created: 2026-07-18
last_updated: 2026-07-18
owner: quant-orchestrator
status: Superseded
tags: [quant, sr, v2, displacement-origin, adequacy, causal, kiss]
superseded_by: plans/architect-to-coder-sr-v2.0-displacement-origin-adequacy-v2.md
source_base: 4dd1f74d22dc0296c3d09599ef75906a7d0f147a
target_agent: Codex quant-coder
---

# SR-V2.0 — Displacement-Origin Adequacy

## Objective

Implement and evaluate one falsifiable hypothesis:

> A compact price range immediately preceding a strong, structure-breaking
> directional displacement has greater first-revisit reaction quality than a
> deterministic side/time/volatility/width-matched naive zone.

This is a development-only adequacy study, not production integration,
parameter optimization, or deployment.

One approval authorizes the complete scope below: typed configuration, pure
detector, study, evidence, compatible visualization payload, tests, validation,
and coder-to-review handoff. No separate architecture or test-plan approval is
required.

## Starting State

- Branch from clean main at
  4dd1f74d22dc0296c3d09599ef75906a7d0f147a.
- Create feature/sr-v2.0-displacement-origin-adequacy.
- Canonical implementation remains src/libs/models/sr.
- src/libs/sr remains reference-only: no import, edit, adapter, copied runtime
  code, configuration fallback, or migration shim.
- The legacy order_block.py may be read only as historical design input.
- Preserve compatibility facades, import boundaries, and zero-cycle invariant.

## Research Contract

### Frozen inputs

- Venue: binance_usdm.
- Asset/timeframe: TAOUSDT, 1d.
- Reuse the verified 629-row development source:
  research/tmp_sr_v1_7/source/6b5a0a81117ba299516fb67ca2da81b3cb6e6f35ed6a85986a27689205a565d9
- Source id:
  6b5a0a81117ba299516fb67ca2da81b3cb6e6f35ed6a85986a27689205a565d9
- Range: 2024-04-11T00:00:00Z through 2025-12-31T00:00:00Z.
- Exact UTC daily grid.
- ATR: point-in-time Wilder RMA, period 14, SMA seed, common start 28.
- No provider call, source refresh, row replacement, holdout, or contaminated
  811-row parent.

### Locked detector baseline

Add one immutable typed contract with no Python numeric defaults:

- displacement_atr: 1.5
- minimum_body_fraction: 0.70
- structure_lookback_bars: 5
- base_search_bars: 3
- atr_method: wilder_rma
- atr_period: 14
- atr_seed: sma

All values live in one new strict V2 trial YAML under configs/sr_trials.
Unknown, missing, duplicate, non-finite, Boolean-as-number, or out-of-range
values fail closed. Do not add them to V1 configs/sr.yaml.

For each newly closed confirmation bar t:

1. Require valid previous-bar ATR at t-1.
2. Compute body abs(close-open) and full range high-low.
3. Require non-zero range.
4. Require body >= 1.5 * ATR[t-1].
5. Require body/range >= 0.70.
6. Bullish requires close > open and a strict close above the maximum high of
   the five completed bars immediately before t.
7. Bearish mirrors this with a strict close below the minimum low.
8. Search backward t-1 through at most three bars for the nearest strictly
   opposing candle. Doji is neither.
9. If no opposing base exists, emit no candidate.
10. Geometry is the base candle full [low, high] range:
    center=(high+low)/2 and half_width=(high-low)/2.
11. Reject non-finite or non-positive geometry.
12. Bullish emits SUPPORT; bearish emits RESISTANCE.
13. formed_at is base close; available_at is confirmation close;
    atr_at_creation is confirmation-bar point-in-time ATR.
14. Source is exactly displacement_origin_v2.
15. Emit at most one candidate per confirmation bar in canonical order.

Closed bars only. No future bar, later ATR, full-window statistic, centered
transform, backfill, repainting, or same-bar pre-close availability.

### Evaluation unit

V2.0 evaluates immutable candidate zones before lifecycle/engine integration,
isolating detection from V1 lifecycle, association, capacity, and reinforcement.

- Visible only after available_at.
- First eligible touch starts one completed bar later.
- Touch is inclusive OHLC intersection with the rectangular band.
- Search expires after 50 bars or fold end.
- Outcome horizon is 10 bars and must remain in the same fold.
- Quality = favorable_reference_atr - adverse_reference_atr.
- Censoring, warm-up, invalid ATR, incomplete horizons, and fold boundaries are
  explicit and exhaustively accounted.
- Duplicate candidate ids are forbidden.
- Nearby/overlapping candidates are not silently merged. Report overlap as a
  diagnostic; engine association is a V2.1 question only after adequacy passes.

### Matched naive controls

Reuse neutral V1.9 control and first-touch semantics without importing a
canonical sibling study or historical script facade:

- two deterministic controls per eligible real anchor;
- match fold, side, anchor time, reference ATR, and zone half-width;
- identical offset, horizon, censoring, and fold-local rules;
- deterministic identity-bound generation;
- exhaustive rejection precedence and one-to-one accounting.

### Folds and decision gates

Reuse six development folds:
2024_q3, 2024_q4, 2025_q1, 2025_q2, 2025_q3, 2025_q4.

Readiness:

- completed real outcomes >= 24;
- comparable folds >= 4;
- completed real outcomes per comparable fold >= 4;
- controls per side per comparable fold >= 4.

Utility, only after readiness:

- pooled median excess quality >= 0.10 ATR;
- positive comparable-fold fraction >= 0.60;
- worst comparable-fold excess >= -0.10 ATR.

Allowed dispositions:

- DISPLACEMENT_ORIGIN_BEATS_NAIVE_NULL
- DISPLACEMENT_ORIGIN_NOT_BETTER_THAN_NAIVE_NULL
- INSUFFICIENT_EVIDENCE

Aggregate gates are authoritative; fold details are diagnostics. Unknown gate
categories, incomplete accounting, non-recomputable metrics, identity mismatch,
or artifact tampering fail closed.

## Scope and Ownership

### Additive core

Preferred ownership:

- config/sections.py: additive DisplacementOriginConfig, exported without
  entering V1 SRConfig/resolver/hash;
- detection/displacement_origin.py: pure causal detector;
- detection/__init__.py: explicit export.

If graph impact shows sections.py unnecessarily destabilizes V1, use a cohesive
new core config module. Model parameters must not live in research or detector
implementation.

Do not modify SREngine.step, V1 pivot behavior, V1 DetectionConfig, SRConfig,
ResolvedSRConfig, configs/sr.yaml, association, lifecycle, checkpoint/replay
schemas, or production selection.

### Canonical study

Create:
src/libs/models/sr/research/studies/displacement_origin_adequacy/

Use small cohesive modules for:

- strict config and frozen identities;
- causal prefix replay;
- first-touch/control construction;
- fold metrics and gates;
- semantic artifact validation;
- CLI;
- immutable viewer-compatible payload.

The study may use core/evaluation and neutral research services. It may not
import sibling studies, historical scripts, providers, network clients,
databases, sealed services, or viewer tooling.

Add a script facade only if an existing supported CLI convention requires it.

### Evidence

Publish content-addressed development evidence under ignored
research/tmp_sr_v2_0/. Generated evidence is never committed.

Required content:

- source/config/implementation identities;
- detector opportunities and rejection accounting;
- candidates, touches, completed/censored outcomes, and controls by side/fold;
- favorable/adverse/quality metrics;
- gate payload and recomputed disposition;
- width-in-ATR, base-distance, and overlap diagnostics;
- immutable case records sufficient for independent recomputation;
- viewer-compatible payload showing all zones by default with focus filtering.

Use shared artifact publication, canonical JSON, manifest, provenance, path
safety, regular-file validation, and content addressing. Public validation must
recompute semantics.

Visualization is diagnostic and cannot override a machine gate. Reuse the
current Lightweight Charts contract where possible. Avoid JavaScript changes.
Browser smoke is required only if JavaScript changes and remains separate from
the research disposition.

## Implementation Order

1. Create branch and record clean base.
2. Run codebase-memory impact for config exports, detection, neutral metrics and
   controls, artifacts, and payload consumers.
3. Add typed config and strict YAML tests.
4. Implement detector and invariant tests.
5. Implement prefix replay and batch/prefix parity.
6. Implement the self-contained canonical study.
7. Implement artifacts, semantic validation, CLI, and compatible payload.
8. Evaluate twice from the same implementation commit; require identical bundle
   ids and member bytes.
9. Run focused, architecture, full SR, Ruff, compile/import, diff, frozen-hash,
   V1.12 semantic, and adversarial artifact checks.
10. Commit code/tests, then coder-to-review handoff. Do not merge.

## Required Tests

Detector:

- bullish support and bearish resistance;
- exact base selection at one, two, and three bars;
- no opposing base and doji behavior;
- each threshold independently failing;
- strict-break ties rejected;
- ATR[t-1] threshold and confirmation ATR binding;
- exact geometry, side, source, formation, and availability;
- no pre-confirmation or future sensitivity;
- invalid order/state/duplicate/non-finite/zero-width inputs;
- deterministic identity/order, one candidate maximum;
- prefix replay equals one-pass causal replay.

Config/architecture:

- missing/unknown/duplicate keys and invalid numeric values;
- V1 resolution, provenance, config hash, and bytes unchanged;
- no libs.sr, core-to-research, research-to-tools, or sibling imports;
- no new cycle; exact public export identity.

Study/evidence:

- half-open folds, same-fold horizons, offset-one touch, 50-bar expiry;
- support/resistance symmetry;
- deterministic matched controls;
- exhaustive one-to-one accounting;
- readiness blocks utility;
- all three dispositions and unknown-gate rejection;
- semantic tamper detection;
- duplicate keys, unexpected/missing/changed members, symlinks, non-regular
  members, bundle symlink, and symlinked-parent rejection;
- two evaluations byte-identical.

## Acceptance Criteria

- Exactly one price-only displacement-origin family is implemented.
- No hidden defaults, alternate grid, optimizer, or feature score.
- No V1 behavior/hash/artifact or legacy dependency change.
- No provider, holdout, production, or trading decision.
- Frozen identities validate before evaluation.
- Candidate/control/outcome/censoring/gate accounting recomputes exactly.
- Two evaluations are byte-identical.
- Focused/full SR, plain architecture, Ruff, compile/import, diff, semantic CLI,
  and adversarial checks pass.
- Coder handoff records commits, bundle/study ids, member hashes/bytes, counts,
  gates, disposition, validation, and dirty state.

## Protected Evidence

Must remain exact:

- V1.12 bundle:
  fd3eaf4cb58a23ee47c0f8645a3d4affd09ef05bf3cafb74831621826a58c206
- V1.12 audit:
  cd452938e2befc66f0d2a4e12d79083b88cf6e03a3124180c356d56a6f2b8adb
- V1.12 disposition: INSUFFICIENT_REINFORCEMENT_EVIDENCE
- configs/sr.yaml SHA-256:
  0c7c11aea8f1ea1e11ef810a6f38d7370a14834c1517d4aab43ac71c378a2119
- V1.12 YAML SHA-256:
  8a1c2f2c72213e62638ead381c0f7a50a67d96b527f799afe878065d59b93665
- V1.12 manifest SHA-256:
  c2d0e03f43ea1154bac9c005a2c4d021188a33f56d4ddd17dd6376b9f77c43e6
- V1.12 audit file SHA-256:
  41bd97da3cef62f10a96f263ac0278e0aff524ebe8337abce0aee986995fee32

## Explicit Non-Goals

No V2 production integration; SREngine/V1 pivot/lifecycle/association/fakeout/
reinforcement/capacity redesign; parameter grid; sensitivity; per-asset
optimization; threshold adjustment after results; ZigZag; fractal; FVG;
liquidity sweep; volume POC; VWAP; TPO; trendline; regime; multi-timeframe;
indicator; order flow; ML; ensemble; confluence; provider/network/database;
holdout; legacy edit/import/deletion; evidence commit; or merge.

## Decision Routing

- BEATS_NAIVE_NULL: recommend separately approved V2.1 engine integration and a
  very small sensitivity/holdout protocol. Do not integrate/open holdout now.
- NOT_BETTER: close V2 without rescue tuning/features and return to V3
  hypothesis selection.
- INSUFFICIENT: distinguish sparse candidates, touches, and censoring. Do not
  relax thresholds or fetch data without a separate source plan.

No disposition authorizes production or trading.
