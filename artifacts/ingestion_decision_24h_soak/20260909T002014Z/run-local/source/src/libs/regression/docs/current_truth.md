# Regression current truth

The supported regression surface is a causal, descriptive context pipeline:

1. `ConfigResolver` loads the canonical YAML and preserves its source-config
   identity.
2. `compute_structural_estimate()` computes the exact unweighted all-pairs
   Theil-Sen log-price line over the final configured causal window.
3. `compute_structural_channel()` derives the asymmetric residual-quantile
   channel from that authoritative line.
4. `compute_regression_context()` derives signed location, deterministic width,
   strict outer-breach flags, and at most one causal previous-channel state.

The approved identities are:

```text
estimator: theil_sen_log_price_all_pairs_v1
channel: asymmetric_residual_quantiles_linear_v1
context: structural_channel_location_one_step_v1
```

The Decision feature is `REGRESSION_CONTEXT@1`. Its history requirement is
resolved as `window_size + 1`, and its projection fails closed for an open or
projected Decision bar. The R3B Momentum observer consumes this context only
as a shadow analytical lane and always returns no decision.

Regression is not a directional signal, optimizer, execution engine, or
standalone alpha model. The fixed R3C2 replication did not reproduce the
declared Momentum-fusion hypothesis; that negative disposition is authoritative.

The old plugin, pipeline, state, MTF/universe, optimization, and CLI surfaces
were retired after their external ownership dependencies were removed. Do not
reintroduce compatibility shims or simplify the retained configuration shape
without a separately certified identity phase.
