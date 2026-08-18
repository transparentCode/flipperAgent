# R3C2 4h Short-Momentum Overextension Replication

Status: `STUDY_COMPLETE`

This deterministic PIT-safe study evaluates only the predeclared short-Momentum
LOWER_OUTER_BAND versus BELOW_OUTER contrast. It does not search alternatives,
define a fusion rule, or recommend promotion.

- Primary horizons: `[2, 4, 8, 16]` 4h bars
- Region A: `LOWER_OUTER_BAND`
- Region B: `BELOW_OUTER`

## Return-spread sign matrix

| member | h2 | h4 | h8 | h16 | provenance |
|---|---:|---:|---:|---:|---|
| btc_4h_candidate_normalized | negative | negative | negative | negative | canonical_normalized_artifact |
| btc_4h_saturating_normalized | negative | negative | negative | positive | canonical_normalized_artifact |
| eth_4h_tv_research_input | positive | positive | positive | negative | research_input_noncanonical |

No automatic approval or promotion disposition is emitted.
