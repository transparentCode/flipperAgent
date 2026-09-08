---
goal: Independently approve the corrected Trendlines V4 N1 exact-identity and observational-persistence evidence
stage: orchestrator-decision
phase: TRENDLINES-V4-N1-EXACT-IDENTITY-PERSISTENCE
status: APPROVED
date: 2026-09-06
owner: quant-orchestrator
worktree: /Users/kajukatli/.devspace/worktrees/flipperAgent-cd309574
base_sha: d901474ffc290d1457e02bcbafcabaddd2de7b42
production_change: NONE
n2_authority: NOT_AUTHORIZED
commit_merge_push: NOT_AUTHORIZED
---

# Trendlines V4 N1 — final approval v1

## Disposition

N1 is approved after independent review and the bounded cutoff-metadata remediation.

Conclusion:

```text
EXACT_IDENTITY_PERSISTENCE_SUPPORTED
```

This conclusion means exact anchor/bar-span geometry identity is deterministic and useful for observational persistence accounting. It does **not** mean the current `pivot_window=3`, `history_capacity_bars=300` baseline has low churn or is already calibrated.

## Independent evidence checks

The orchestrator independently authenticated the corrected artifacts and recomputed their identity relationships:

```text
windows:                         16
bad cutoff ranges:               0
first BTCUSDT 1h early range:    [7476, 7775]
required rule:                   [start+300, start+599]
report SHA matches manifest:      yes
report byte length matches:       yes
manifest_id recomputes exactly:   yes
```

The full N1 measurement tape was independently re-executed before remediation and matched the published aggregate evidence exactly:

```text
measured snapshots:              4,800
role observations:               19,200
side snapshot pairs:             9,600
unique exact geometries:         1,159
role episodes:                   2,363
global role availability:        0.9943229166666666
replacement count:               2,278
replacement rate / 100:          11.904264214046822
reappearance episodes:           376
median episode lifetime:         6 bars
p90 episode lifetime:            16 bars
p95 episode lifetime:            21 bars
maximum episode lifetime:        132 bars
```

The remediation changed only evidence metadata arithmetic and its regression. The frozen aggregate values remained unchanged.

## Important interpretation for N2/H0

Persistence is supported, but the current baseline is not especially low-churn.

Role-level evidence includes approximately:

```text
support.structural:      median 8 bars; replacement 8.86 / 100
support.current_valid:   median 5 bars; replacement 13.32 / 100
resistance.structural:   median 8 bars; replacement 10.58 / 100
resistance.current_valid:median 4 bars; replacement 14.86 / 100
```

Current-valid roles are therefore observably more dynamic than structural roles. N2 and later H0 must treat this as baseline behavior, not assume that persistence support implies long-lived geometry.

## Protected production locks

Final protected hashes remain exact:

```text
c92076e72891b222cf8359cba614c8ed969f04d1734a8985abdb0b68ffc9509f  src/libs/models/trendlines_v4/core.py
66ccb45f10ab0c3b530f81919ad172fdde93b51cda04d935a6ce581641d0ac61  src/libs/models/trendlines_v4/__init__.py
9d65b6f1cc0d00bbd60c9f40299f47701a161eadc2d5d0ae29b28747d415e523  src/libs/models/trendlines_v4/adapters/decision_plugin.py
41d9d9562e48c54042b46ce9880247b4ba23769ff80d708c2ee7c15c951ee763  src/apps/decision_app/composition.py
```

Corrected final N1 artifacts:

```text
30045237ff1bd763539addbf5645dadb862665512854731b1fdf3823c5499bd3  artifacts/trendlines_v4/n1_exact_geometry_identity_persistence_v1/report.json
9e270831b656e13b3df0e8c4cbb90e2ebeec4f24a9c5c56555c71b6d7506d464  artifacts/trendlines_v4/n1_exact_geometry_identity_persistence_v1/manifest.json
```

## Authority boundary

Approved:

```text
N1 exact identity and observational persistence evidence
```

Not authorized by this approval:

- N2 current-relevance implementation;
- production geometry identity fields;
- lifecycle state;
- fuzzy tracking;
- relevance scores or filters;
- H0/H1/H2 hyperparameter work;
- N3 secondary geometry;
- N4 multi-timeframe fusion;
- production config changes;
- commit, merge, or push.

N1 is complete.

TRENDLINES_V4_N1_EXACT_IDENTITY_PERSISTENCE_APPROVED
NEXT_OWNER_CAN_ACT_WITHOUT_GUESSING
