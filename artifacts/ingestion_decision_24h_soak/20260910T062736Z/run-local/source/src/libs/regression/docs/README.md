# Certified regression context

`libs.regression` provides descriptive market geometry for Decision context.
It is not a standalone directional-alpha, execution, or optimizer stack.

## Current path

```text
canonical YAML + ConfigResolver
        ↓
exact all-pairs Theil-Sen log-price structural estimate
        ↓
asymmetric residual-quantile channel
        ↓
location, breach, and one-step causal re-entry snapshot
        ↓
Decision REGRESSION_CONTEXT@1
```

The structural estimator is `theil_sen_log_price_all_pairs_v1`. It fits the
approved unweighted all-pairs Theil-Sen line in elapsed-hour units over the
configured causal window. The channel is
`asymmetric_residual_quantiles_linear_v1`, owned by the strict YAML policy
`inner_coverage` / `outer_coverage`. Context snapshots use
`structural_channel_location_one_step_v1`.

The supported public computations are:

```python
from libs.regression.api import (
    compute_regression_context,
    compute_structural_channel,
    compute_structural_estimate,
)
```

`ConfigResolver` and the canonical YAML retain their approved source-config
identity, including legacy-shaped fields that remain part of the hash. R4C
does not simplify or reinterpret that configuration surface.

## Decision and research boundary

Decision projects the context snapshot as `REGRESSION_CONTEXT@1`. The R3B
observer remains shadow-only and never publishes a decision. R3C2 did not
replicate the predeclared Momentum-fusion hypothesis, so regression remains
descriptive geometry and risk/context information rather than standalone
trading alpha.
