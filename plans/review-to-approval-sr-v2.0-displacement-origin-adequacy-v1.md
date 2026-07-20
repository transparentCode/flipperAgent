---
goal: Approve SR-V2.0 as completed, reproducible research with an authoritative INSUFFICIENT_EVIDENCE disposition and no runtime promotion.
stage: review-to-approval
date_created: 2026-07-19
last_updated: 2026-07-19
owner: Quant Review Agent
status: Ready
tags: [handoff, quant, sr, v2, displacement-origin, adequacy, approval]
source_agent: Quant Review Agent
target_agent: Quant Approval Gate
---

# SR-V2.0 Displacement-Origin Adequacy — Review to Approval

## Reviewed Scope

Independent review covered branch
`feature/sr-v2.0-displacement-origin-adequacy`, based on main commit
`4dd1f74d22dc0296c3d09599ef75906a7d0f147a`, through docs HEAD
`1f36ca73c6a1d5fc7acb940e63d8c596c962ca65`.

The reviewed implementation and remediation chain includes:

- `bffaaa4`: initial displacement-origin detector;
- `1598064`: initial adequacy study;
- `0c93096`: corrected directional/ATR detector semantics and introduced
  independently evaluated prior-close naive bands;
- `6899900`: causal confirmation identities and exact per-candidate control
  topology;
- documentation commits through `1f36ca7`.

Reviewed files include:

- `src/libs/models/sr/detection/displacement_origin.py`;
- `src/libs/models/sr/research/studies/displacement_origin_adequacy/`;
- `configs/sr_trials/sr_v2_0_taousdt_1d_displacement_origin_adequacy.yaml`;
- focused detector, study, artifact, runner and architecture tests;
- `plans/coder-to-review-sr-v2.0-displacement-origin-adequacy-v1.md`;
- frozen ignored evidence bundle
  `60d8ac404b4e5a6aaf44eb9325bba7ddf6be154f663aa6a08e7a634bedbe695c`.

The review covered point-in-time ATR ownership, candle direction, opposing-base
selection, prior-close control geometry, independent touch discovery, fold
boundaries, 50-bar expiry, 10-bar outcome horizons, causal identities,
per-candidate control topology, paired metrics, readiness precedence, source
provenance, immutable artifact reconstruction and protected V1.12 evidence.

## Resolved Findings

No blocking, major or minor implementation findings remain.

The full review/remediation cycle resolved:

1. Candidate `atr_at_creation` now uses confirmation-bar ATR while
   displacement qualification remains scaled by prior-bar ATR.
2. SUPPORT requires a bullish confirmation candle and strict upper structural
   break; RESISTANCE requires a bearish candle and strict lower break.
3. The old same-touch pseudo-control was replaced by a real naive band:
   same width, centered on `close[t-1]`, available at confirmation.
4. Real and naive bands discover their touches independently.
5. Primary utility is paired real quality minus completed same-side naive
   quality; opposite-side controls are diagnostic only.
6. Control identity binds a causal `confirmation_id`, not an outcome-bearing
   real case ID.
7. Changing only the future real outcome leaves confirmation identity, control
   records and control IDs unchanged.
8. Study construction rejects missing, extra, reordered and duplicate-side
   controls; every in-fold candidate requires exact ordered SUPPORT and
   RESISTANCE controls.
9. The canonical source capsule and outer cohort source bundle are represented
   and validated as distinct identities.
10. Rehashed artifact changes are rejected through full semantic
    reconstruction.
11. The final handoff validation count was corrected to the independently
    reproduced total of 90.

The corrected implementation satisfies the approved V3 KISS contract without
adding a detector registry, production integration, extra feature family,
control-center parameter or rescue tuning.

## Remaining Non-Blocking Follow-Ups

No V2.0 code, test, evidence or handoff correction remains.

The following are workflow outcomes, not implementation defects:

- Three architect plan drafts remain untracked and must remain excluded from
  any commit or merge unless separately requested.
- The formal result is `INSUFFICIENT_EVIDENCE`, not a production promotion.
- The detector missed the global readiness threshold by one completed pair:
  23 versus 24.
- Diagnostic utility is not encouraging:
  - pooled median paired excess: `0.0 ATR`;
  - positive comparable-fold fraction: `0.0`;
  - worst comparable-fold median: `-0.14263155242029035 ATR`.
- These diagnostics do not override readiness precedence, but they also provide
  no basis for fetching one more observation, loosening rules or tuning this
  hypothesis.
- A new pivot/fractal hypothesis must be a separately approved plan after
  V2.0 closeout. It is not V2.0 remediation.

## Blast Radius Confirmation

The implementation remains isolated to research and one unregistered detector.

Confirmed boundaries:

- `detect_displacement_origins` is not wired into `SREngine`;
- no lifecycle, association, runtime configuration or production consumer was
  changed;
- `configs/sr.yaml` remains protected and unchanged;
- no provider, network, refresh or holdout path was accessed;
- no database, viewer, JavaScript or deployment code changed;
- no legacy `src/libs/sr` dependency was introduced;
- no V2.1 work was started;
- no merge was performed.

The branch may be considered for research-only integration after explicit
approval. Approval must not be interpreted as runtime registration, model
promotion, trading use or deployment authorization.

## Validation Evidence Summary

### Independently reproduced during review

- detector suite: `24 passed`;
- V2 study suite: `32 passed`;
- architecture suite: `34 passed`;
- combined focused total: `90 passed`;
- focused Ruff checks: passed;
- `git diff --check`: passed;
- V2 semantic reconstruction: passed;
- causal identity invariance probe: passed;
- exact per-candidate control-topology rejection probe: passed;
- prior-close geometry and confirmation-ATR probes: passed;
- pair arithmetic probe: passed;
- source/capsule provenance probe: passed.

Semantic reconstruction returned:

- candidates: `28`;
- controls: `56`;
- completed same-side pairs: `23`;
- disposition: `INSUFFICIENT_EVIDENCE`;
- study ID:
  `5d9a85ef87bac80407f969eba244f258ae198a1af508ed1ab27cda079e96360a`.

### Coder validation accepted with matching focused evidence

- full SR suite: `968 passed in 640.17s`;
- full Ruff: passed;
- compileall and package imports: passed;
- deterministic double evaluation: byte-identical;
- protected V1.12 semantic validation: passed;
- protected hashes: unchanged.

### Final immutable evidence

- bundle ID:
  `60d8ac404b4e5a6aaf44eb9325bba7ddf6be154f663aa6a08e7a634bedbe695c`;
- study ID:
  `5d9a85ef87bac80407f969eba244f258ae198a1af508ed1ab27cda079e96360a`;
- manifest SHA-256:
  `223821f50a9e4b2e6329b9441510eb3d46dc32258ef1c298262ca3467c7631f2`;
- study SHA-256:
  `5d7fa49cec06811cd71113e97bf9c0f0a043b3dcf484a512be59b7095536a480`;
- cases SHA-256:
  `1dbc19acb1944e89ad02ecc518c4498662dcf9aaf4a9b798b0cf45cda956fb47`;
- manifest/study/cases byte lengths:
  `6524 / 2879 / 107625`.

Source provenance:

- outer cohort bundle:
  `6b5a0a81117ba299516fb67ca2da81b3cb6e6f35ed6a85986a27689205a565d9`;
- canonical source capsule:
  `d210494937ebcd4347e026b8ac02bff3105065e5455752b8690d449def357925`;
- source ID:
  `fc1ba274454f277a40f005f542fdfd4e6e752e5afa2e1050f3582b21fd8b1120`.

Worktree state contains only the three pre-existing untracked architect plan
drafts.

## Recommended Approval Status

**APPROVE_RESEARCH_ONLY.**

Accept V2.0 as complete and reproducible with the authoritative disposition
`INSUFFICIENT_EVIDENCE`.

Approval may authorize a research-only merge if the user explicitly chooses
to preserve this detector and study infrastructure on main. It must not:

- register or deploy the detector;
- change production configuration;
- open holdout;
- fetch more data;
- relax readiness;
- tune displacement, body, lookback, base-search, control or utility settings;
- reinterpret the result as adequate or useful S/R evidence.

Given the negative diagnostic utility, do not schedule a V2.0 rescue study.

## Recommended Handoff

Route this package to the Quant Approval Gate for final sign-off.

The gate should decide and record:

1. acceptance of the immutable V2.0 research result;
2. research-only merge permission versus archival closeout;
3. explicit non-promotion of the detector;
4. authorization to begin a separate architect-to-coder plan for one causal
   pivot/fractal-zone adequacy hypothesis.

No agent should merge, start V2.1 or alter evidence before that approval
decision.
