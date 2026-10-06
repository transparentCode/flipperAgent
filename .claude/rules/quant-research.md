---
paths:
  - "src/libs/models/**"
  - "src/libs/sr/**"
  - "src/libs/regression/**"
  - "src/libs/analysis_capabilities/**"
  - "research/**"
---

# Quantitative research rules

- Treat source code, deterministic tests, frozen contracts, and explicit runtime evidence as authoritative. Historical plans and artifacts are evidence, not current truth.
- Preserve point-in-time availability, causal cutoffs, symbol identity, timeframe identity, UTC/calendar semantics, deterministic replay, and provenance.
- Do not introduce look-ahead, label leakage, survivorship leakage, hidden resampling, or timing changes while refactoring.
- When a contract uses closed native-timeframe bars, preserve that contract and evaluate timeframes independently unless the current approved design explicitly changes it.
- Separate descriptive findings, statistical evidence, research conclusions, and promotion decisions. A positive metric is not production approval.
- Keep holdouts untouched by tuning. Report experiment multiplicity, sensitivity, uncertainty, and failed/null baselines when they affect interpretation.
- Prefer the smallest experiment or implementation that can falsify the current hypothesis. Do not add parameters or abstractions solely to improve an observed score.
- For benchmarks, record the evaluated universe, period/cutoffs, sample counts, configuration, and reproducibility evidence already expected by the surrounding research package.
