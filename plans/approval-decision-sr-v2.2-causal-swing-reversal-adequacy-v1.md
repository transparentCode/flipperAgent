---
goal: Close SR-V2.2 causal swing-reversal adequacy as approved negative research evidence.
stage: approval-decision
date_created: 2026-07-19
last_updated: 2026-07-19
owner: Quant Orchestrator
status: Approved
tags: [handoff, quant, sr, v2-2, research, negative-result]
source_agent: quant-approval
target_agent: Quant Orchestrator
---

# SR-V2.2 causal swing-reversal adequacy — approval decision

## Approval scope

Approve frozen TAOUSDT/1d V2.2 evidence only. Implementation commit:
`5340c519a502c67afc0a9715c962374630a6a91f`. Documentation handoff commit:
`ba58a90dc09fc0a9328e9853ea07873d562381be`.

Bundle `e50c0a2237c5e909d148eab39a19e75f76037d29c6f92d4a316c348190b47660`
semantically reconstructs study
`34e44ea7c16384bd98bbc99aef162d4f9a516ae0b6ca2e4cc52d75a894e4c846`.

## Blocking issues

None.

## Blast radius confirmation

V2.2 added one unregistered, pure causal swing detector and one isolated
research-study package. Shared first-revisit/control helpers were consumed
unchanged. V1, V2.0, V2.1, runtime, lifecycle, replay, viewer, configuration
surface, provider, and holdout behavior did not change.

Protected evidence remains valid:

- V2.1: `PIVOT_REJECTION_NOT_BETTER_THAN_NAIVE_NULL`.
- V2.0: `INSUFFICIENT_EVIDENCE`.
- V1.12: `INSUFFICIENT_REINFORCEMENT_EVIDENCE`; frozen manifest and audit
  hashes remain exact.

## Validation sufficiency

- Reviewer reproduced 37 causal detector/study tests and exact semantic bundle
  reconstruction.
- 35 completed matched pairs passed all readiness gates.
- Pooled median paired excess: `0.09259058053905056 ATR` vs required `0.10`.
- Positive comparable-fold fraction: `0.80` vs required `0.60`.
- Worst comparable-fold median: `-1.1099568460331941 ATR` vs required `-0.10`.
- Ruff and `git diff --check` passed. Coder recorded 1002 passing full SR tests;
  reviewer connector window expired before independently capturing that final
  command output.

## Residual risk

Approval does not prove adaptive or probabilistic swing models fail. It rejects
only globally fixed 1.5-ATR swing selection on this frozen TAOUSDT/1d cohort.
Severe adverse-fold instability means small pooled miss is not near-production
evidence.

## Approval decision

**APPROVE_RESEARCH_ONLY.** Final disposition remains
`SWING_REVERSAL_NOT_BETTER_THAN_NAIVE_NULL`.

## Required handoff

Do not merge, tune 1.5 ATR, open a holdout, contact providers, wire runtime,
or promote V2.2. V2.3, if pursued, starts with one separate architect handoff
covering continuous causal swing salience, asset/timeframe-relative
normalization, hierarchical probability calibration, and fresh multi-asset /
timeframe evidence. No V2.3 code is authorized by this decision.
