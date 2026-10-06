---
name: research-gate
description: Independently challenge quantitative research evidence before accepting a conclusion or promotion decision.
context: fork
agent: quant-architect
background: false
disable-model-invocation: true
---

Review $ARGUMENTS as an independent quantitative evidence gate.

Reconstruct the claim from the live code, experiment contract, tests, and authorized artifacts. Challenge point-in-time correctness, leakage, labels, temporal/asset splits, holdout integrity, baselines/nulls, normalization, numerics, reproducibility, experiment multiplicity, sensitivity, and uncertainty.

Separate:

- what the evidence directly establishes;
- what remains an inference;
- what is contradicted or unsupported;
- whether the research conclusion is POSITIVE, NEGATIVE, or INCONCLUSIVE;
- what additional evidence would materially change that conclusion.

Do not turn a valid research conclusion into a production-promotion decision. Do not edit files.
