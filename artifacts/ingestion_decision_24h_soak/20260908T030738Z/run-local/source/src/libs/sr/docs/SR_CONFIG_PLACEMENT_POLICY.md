# SR Config Placement Policy

This document is the compact execution reference for the approved SR config placement policy.

It serves two purposes:

- the ordered placement decision procedure required by the policy plan, and
- the non-kernel placement summary that complements the kernel-focused detail in `app/sr/docs/KERNEL_CONFIG_CATEGORIZATION.md`.

The full field-by-field source of truth remains `plan/design-sr-config-placement-matrix-1.md`. This document is the shorter operational reference for engineers updating `app/sr/config/sr.yaml`, the resolver, and the optimizer surface.

## 1. Placement Decision Procedure

Apply these rules in order. Stop at the first rule that explains the knob cleanly.

1. Asset fact
   Place structural market facts in `asset_metadata`.
   Examples: trading hours, session-gap existence, round-number mode, gap-handling profile.
2. Rule-derived formula
   Place configurable coefficients for derived formulas in `sr.rule_derived.*`.
   Examples: pivot multipliers, breakout horizons, inactivity formulas.
3. Runtime-only input
   Do not place runtime-computed values in YAML.
   Examples: ATR, live round interval, profile histograms, injected regression results.
4. Global heuristic
   Place shared guardrails, scoring caps, architecture flags, and execution defaults in `sr.*`.
   Examples: `max_age_bars`, output colors, audit retention, router worker counts.
5. Per-timeframe low-tune
   If the knob is resolution-sensitive but not symbol-residual, allow `per_tf.{tf}` over a global `sr.*` default.
   Examples: lookback bars, smoothing windows, histogram granularity.
6. Asset residual default
   If the knob reflects persistent symbol-level detection strictness not already explained by metadata or `per_tf`, allow `assets.{symbol}.defaults.*`.
7. Asset plus timeframe residual
   Allow `assets.{symbol}.{tf}.*` only for proven high-sensitivity residuals. This layer is default-deny and requires explicit evidence.

Two extra rules always apply:

- Placement eligibility is separate from optimizer eligibility.
- Use the shallowest valid layer that explains the behavior robustly.

## 2. Non-Kernel Placement Summary

| Section / Field Family | Default Layer | Allowed Override Depth | Initial Optimizer Status | Notes |
|-|-|-|-|-|
| `asset_metadata.profiles.*` structural facts | `asset_metadata.profiles.*` | Per-asset metadata only | No | Structural market facts never migrate into kernel tuning. |
| `asset_metadata.assets.{symbol}.profile` | `asset_metadata.assets.{symbol}` | Per-asset only | No | Canonical asset-to-profile selector. |
| `sr.pipeline.enabled_kernels` | `sr.pipeline` | Up to asset+TF | No | Operational feature-selection surface, not an optimizer knob. |
| `sr.pipeline.{atr_period,avg_volume_window,merge_threshold_pct_atr}` | `sr.pipeline` | Global only | No | Shared normalization and deduplication heuristics. |
| `sr.ensemble.method` | `sr.ensemble` | Global only | No | Architectural selector. |
| `sr.ensemble.structural_vs_micro_ratio` | `sr.ensemble` | Per-TF approved, per-asset conditional | Initial | Shared initial optimizer knob; deeper placement remains constrained. |
| `sr.ensemble.kernel_weights` | `sr.ensemble` | Per-TF approved, per-asset conditional | Later | Allowed to vary shallower than asset+TF by default. |
| `sr.ensemble.confidence.*` and calibration caps | `sr.ensemble` | Global only | No | Stable scoring semantics. |
| `sr.lifecycle.age_lambda` | `sr.lifecycle` | Per-TF approved, per-asset conditional | Initial | Shared first-pass optimizer knob. |
| `sr.lifecycle.min_strength` and `breakout_atr_threshold` | `sr.lifecycle` | Per-TF approved | Later | Resolution-sensitive but not first-pass optimizer defaults. |
| Rule-derived lifecycle horizons | `sr.rule_derived -> sr.lifecycle override` | Per-TF shallow override only | No | Default to formulas, not deep overrides. |
| Lifecycle guardrails and semantics | `sr.lifecycle` | Global only | No | Keep lifecycle behavior stable. |
| `sr.enhancement.stop_hunt_pierce_atr` | `sr.enhancement` | Per-TF approved, deeper conditional | Later | Research candidate, not first-pass optimizer surface. |
| `sr.enhancement.volume_spike_threshold` | `sr.rule_derived -> sr.enhancement override` | Per-TF shallow override only | No | Derived by formula by default. |
| Stable semantic feature thresholds | `sr.features` | Per-TF conditional only | No | Keep semantic thresholds stable unless explicitly promoted. |
| Explicit feature bar-count horizons | `sr.features` | Per-TF approved | No | Resolution-sensitive but not optimizer-owned. |
| Metadata-derived feature lookback hours | `asset_metadata.profiles.*` | Shallow override only | No | Remain metadata-led by default. |
| `sr.regime.{enabled,min_confidence,max_entropy,stability_window_bars}` | `sr.regime` | Per-TF approved | No | Gate semantics may vary by resolution, not by asset. |
| `sr.regime.{confidence_ema_alpha,fallback_state,weights.*,fallback_weights.*}` | `sr.regime` | Global only | No | Global fallback and weighting policy. |
| `sr.cross_asset.correlation_threshold` and `min_universe_agreement` | `sr.cross_asset` | Per-TF approved | No | Analyzer thresholds stay universe-wide. |
| `sr.cross_asset.sector_cluster_eps_atr` | `sr.cross_asset` | Per-TF approved | Initial | Initial non-kernel optimizer knob. |
| Cross-asset scoring caps and limits | `sr.cross_asset` | Global only | No | Resource and scoring guardrails. |
| `sr.universe.{max_workers,timeout_per_asset_s,cross_asset_enabled}` | `sr.universe` | Global only | No | Execution-layer router settings. |
| `sr.universe.{correlation_threshold,min_universe_agreement}` | `sr.universe` | Global only | No | Execution-layer duplicates; not optimizer-owned. |

## 3. Practical Rules

- Put metadata in `asset_metadata`, not in `sr.kernels.*`.
- Put formulas in `sr.rule_derived.*`, not in per-asset overrides.
- Treat `assets.{symbol}.{tf}` as an exception layer, not a default destination.
- Do not infer optimizer eligibility from placement eligibility.
- When a field is ambiguous, keep it shallower and require evidence before promoting it deeper.