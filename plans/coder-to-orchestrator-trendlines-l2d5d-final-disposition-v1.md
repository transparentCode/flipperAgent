# Coder-to-Orchestrator Handoff — L2-D5D Final Disposition

## Scope

- Branch: `research/trendlines-adequacy-v1`
- Starting commit: `bd419f38027217a2ea3fdad5e31517f1954ba211`
- Parallel-main audit: `origin/main` remains Trendline V2 viewer-only; no
  mature-trendlines or shared replay/identity overlap.
- No commit, merge, provider call, model execution, replay execution, or
  parameter trial performed by D5D.

## Frozen evidence chain

- D5A source matrix: `9e324fff3bfce51eadb86fdcc173d75e984064d7eeaccb3d413fc4c8b13e907a`
- D5B protocol: `b722750e2b4deb627bec302431101e2a7d54b43a886af351d99c3be77819b639`
- D5B replication bundle: `b0eff1ecd259af4193f70d6ada991a3f7ef0e8731bece95ffd02c15045c7da9b`
- D5C protocol: `f59c285a453138c0c2b09dba9f28911b0a14a776e02be6d4caaa0e0964300e47`
- D5C compact aggregate: `26247da3bd7a76a169112c9bb36284fc91c2f5946ef624493d2f3b857cb6acd7`
- Reference D2: `f74fcfe1a16c0a3b489aeb61090c861d49c91fc578a31c9217673d8b581d254f`
- Reference D3: `56d42daeda8bfcfd6625a345c4aef40a9eb9bf63ced415f4a947b9ff546d93a4`
- Reference D4A: `664a23b5110cea4a3f9370df9d465da3c07c70ceaaae96f29ad8841f31bb7663`
- Reference D4B: `98f04441c0ef9c643640c78004a875ab6fa6a8de6c797eb1f2e68420910323db`

All prior checksum inventories and content IDs were verified before synthesis.

## Frozen decision protocol

- Cohorts: reference BTCUSDT 1h, temporal BTCUSDT 1h, ETHUSDT 1h, SOLUSDT
  1h, BTCUSDT 4h.
- Roles: support and resistance.
- Horizons: 1, 3, 6, 12 bars.
- Primary utility measure: touch rate.
- Secondary measures: rejection, confirmed/false break, penetration,
  favourable excursion, adverse excursion.
- Nulls remain separate: random valid pivot pair versus causal
  density-matched geometry.
- Sensitivity: dense 2/2/2 and sparse 4/4/4; different event populations are
  descriptive, not paired causal effects.
- Exact outcome hierarchy: coverage failure, adequate further research,
  utility not better than naive null, structurally stable but no utility,
  excessive churn, residual ambiguity.

## Cohort synthesis

All five cohorts classified `OBSERVED_NONTRIVIAL_STRUCTURE`. Random-pair
robust-positive touch cells were 8, 4, 7, 8, and 8 respectively; density-
matched robust-positive cells were zero for every cohort. Every dense and
sparse capsule had zero coarse-event Jaccard in committed D5C evidence, so
all five cohorts are `PARAMETER_FRAGILE`.

The final synthesis selects:

```text
outcome:          UTILITY_NOT_BETTER_THAN_NAIVE_NULL
recommended:      REDESIGN_GEOMETRY_SELECTION
decisive rule:    RULE_3_UTILITY_NOT_BETTER_THAN_NAIVE_NULL
```

“Naive null” is historical enum vocabulary. The decisive comparator is
`causal-density-matched-null-v1`, the stronger utility comparator. Decisive
evidence is causal density-matched null failure; random-pair superiority alone
is insufficient.
No adequacy, promotion, or production conclusion was selected beyond this
research disposition.

## D5D-R1 closeout remediation

- Decision-matrix `passed` values now independently evaluate each frozen rule;
  `selected` marks only first passed rule in hierarchy order.
- Rule 1 passes only when evidence is incomplete. Official matrix is
  `false/false`, `false/false`, `true/true`, `false/false`, `false/false`,
  `false/false` for Rules 1–6.
- Matrix, review and manifest bind explicit decisive-null identity and legacy
  outcome clarification.
- Published readback reconstructs prior evidence, cohort rows, final bundle,
  complete decision matrix and cohort summaries, then requires exact equality.
- Final bundle and all five cohort evidence IDs remained unchanged.

## Artifact

Output root:
`artifacts/trendlines_research_adequacy/20260727_l2d5d_final_disposition_v1/`

Files: `final_disposition_bundle.json`, `cohort_evidence.json`,
`decision_matrix.json`, `run_manifest.json`, `review.md`, `checksums.json`.

Final content-addressed IDs:

- Protocol: `c2ea4ef0b9e4395455a84e154f6b4403b3e95fedcc6ff68477096ebd36c93b82`
- Bundle: `bdbbb1d70c34564c2b9fa9bacc2f3e1fa5265d833d993c7bfc64bf025a939762`
- Cohort evidence IDs, in frozen member order:
  - `e9a7b6ec938b551fa0eebf79e6b8f1775580d58d3b547117b93666e4406e8e6d`
  - `d7a42aca9befa3ca40113a11fa2321a21c15e761e1318f87d4d8dbff9bfa5d24`
  - `60d9b65ea4fd9ecc9d3afa611432adfc99941eece44463125a10f451a17ae1fa`
  - `61dfadcdc2dd39cfb43c7632852b97878e1aaf9379650a7d5889c699171cf141`
  - `0408926cfb520ba9fd2b51226e4bbec20a942ff7eec8209e2c3f6e352f9b1682`

Final artifact inventory contains six files and five checksum entries. Final
file sizes and SHA-256 values are:

| file | bytes | SHA-256 |
| --- | ---: | --- |
| `cohort_evidence.json` | 65749 | `af78b6f6de4daeb1ae98e9a0a57e1ead5c37edbd0db17f1d49c15ab3a780f5aa` |
| `decision_matrix.json` | 31711 | `a0093acb79a5ad0114858c5df0dd4318a57de2da02730f9c6513f54526fede35` |
| `final_disposition_bundle.json` | 3651 | `91675d2d1e0f666f2db06556a0e5a621ccdcdf7325204201a68055265c197fd9` |
| `review.md` | 2979 | `2a7ff5527b49ad3dc4ad8eeb367f99e883e5cc6a6992623d83c695f1fd2b745e` |
| `run_manifest.json` | 11342 | `9bf5418d370263370bedcc163bb8ecd7aa6b382e7c6779f3c5669f7e730794a7` |

`checksums.json` contains the five rows above and is itself excluded from its
own inventory. Final closeout changed manifest/review/checksum content only;
protocol, bundle and cohort evidence IDs remain unchanged.

## Validation

Validation closeout:

- D5D focused package/script tests: `32 passed`.
- D5C–D5A regression: `130 passed`.
- D4B–D3 regression: `144 passed`.
- Canonical mature trendlines: `796 passed`.
- Viewer Python: `30 passed`.
- Viewer Node: `20 passed`.
- Consumer/bridge: `79 passed`.
- Offline workflows: `20 passed`.
- Ruff, compileall and diff-check: passed.
- Provider calls/retries, model executions, replay executions and parameter
  trials: `0 / 0 / 0 / 0`.
- Artifact readback: six files, five checksums, final bundle/protocol IDs
  recomputed successfully.
- Repository-local caches: `0` after closeout.

Mature trendlines research is formally closed after D5D review. No commit,
merge, cleanup, redesign or production integration is part of D5D.

## Deliberately not added

No scoring engine, optimiser, ranking framework, provider/model/replay runner,
new metric, production path, D6 path, or generic plugin layer.

## Residual limitations

- Five bounded cohorts do not establish market universality.
- D3/null comparisons preserve mature-model event timing.
- Sensitivity variants replace event populations rather than form paired
  causal perturbations.
- No P&L, execution, promotion, or production activation was evaluated.

Mature trendlines research formally closes after D5D review and commit. Later
redesign, cleanup, merge, or production work is a new programme.
