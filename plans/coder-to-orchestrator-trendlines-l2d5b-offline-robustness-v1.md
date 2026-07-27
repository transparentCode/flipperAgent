# L2-D5B — Offline Robustness Replication Handoff

## 1. Disposition

`READY_FOR_L2D5B_ROBUSTNESS_REVIEW`

D5B produced descriptive, offline robustness evidence for four fresh D5A
members. No adequacy outcome was selected. D5C sensitivity and D5D synthesis
remain unstarted.

## 2. Branch and starting checkpoint

```text
branch: research/trendlines-adequacy-v1
implementation base commit: c503bbe0c24a642b5c6478de07c36165f590cad9
provider calls/retries: 0 / 0
worktree scope: authorised D5B paths only
```

Parallel-main audit found only non-overlapping Trendline V2 viewer paths; no
merge or rebase was performed.

## 3. D5A binding

```text
matrix root:
artifacts/trendlines_research_robustness/20260727_l2d5a_source_matrix_v1/

matrix bundle:
9e324fff3bfce51eadb86fdcc173d75e984064d7eeaccb3d413fc4c8b13e907a
```

Reference evidence remained bound in its committed location. D5B did not
copy or reprocess the reference frame.

Reference chain:

```text
D2:  f74fcfe1a16c0a3b489aeb61090c861d49c91fc578a31c9217673d8b581d254f
D3:  56d42daeda8bfcfd6625a345c4aef40a9eb9bf63ced415f4a947b9ff546d93a4
D4A: 664a23b5110cea4a3f9370df9d465da3c07c70ceaaae96f29ad8841f31bb7663
D4B: 98f04441c0ef9c643640c78004a875ab6fa6a8de6c797eb1f2e68420910323db
```

## 4. Fixed member order

```text
1. temporal-btcusdt-1h-20250401-v1
2. cross-asset-ethusdt-1h-20250401-v1
3. cross-asset-solusdt-1h-20250401-v1
4. cross-timeframe-btcusdt-4h-20250401-v1
```

Each member had 312 bars, replay positions `19 → 311`, recording start 64,
record stride 1, 293 executed prefixes and 248 recorded positions.

## 5. Replication protocol

```text
replication_protocol_id:
b722750e2b4deb627bec302431101e2a7d54b43a886af351d99c3be77819b639

replay: warmup=19, record_start=64, end=311, every=1, signals=true
study: minimum_warmup_bars=45, minimum_prior_executed_prefixes=45
stability horizons: 1, 3, 6, 12
interaction horizons: 1, 3, 6, 12
quantiles: 0.05, 0.95
deterministic baseline IDs:
  ddf18905d6cad86f78d83ea45298531f329de23ac4afd214811c181538e3a930
  22e405ce85d3fda2352080942e631240e5c9f505cfe187764d9084913856d8c3
stochastic baseline IDs:
  c34573875135b4bfe723ca1f885150524a9b849ba7949b2f84f1258435571e1e
  554f85bb1eea413ac1afabd6acbe4db469f845cdf2d297c64205d4bb71cc8401
stochastic repetitions: 32 each
```

The 1h members resolved `signals.hold_bars=3`; BTCUSDT 4h resolved
`signals.hold_bars=1`. Interaction identities were therefore member-specific.

## 6. Member identities and result inventories

| member | timeframe | hold | D5A spec/evidence | source / availability / dataset | preparation | D2 / D3 / D4A / D4B result IDs |
|---|---:|---:|---|---|---|---|
| temporal BTCUSDT | 1h | 3 | `7cb30d53` / `8bab3488` | `1c80f2d3` / `e58847be` / `1e462fc4` | `f9700b6f` | `d089eaf9` / `4a688ce9` / `547340f1` / `0ab4b7b1` / `d8d9e81e` |
| cross-asset ETHUSDT | 1h | 3 | `9bdca6c7` / `c251ec80` | `d0e6daec` / `d00aae3d` / `6ec815da` | `ceee946b` | `e4ea0145` / `cc406624` / `5d12f855` / `5f08e62b` / `e610764d` |
| cross-asset SOLUSDT | 1h | 3 | `29e27918` / `4bb550cc` | `ce5da895` / `d6087914` / `6304a657` | `4a1b76ca` | `33ca0779` / `509ae5ea` / `439dd23d` / `7dbbf431` / `241c12f6` |
| cross-timeframe BTCUSDT | 4h | 1 | `ea5dbc8d` / `d8ed2c4d` | `362b8123` / `e23bcb4a` / `db7d1cfd` | `855474cc` | `4ea94e27` / `a173cee2` / `16eeee71` / `eb1697ed` / `f95fde87` |

Table values are prefixes. Full 64-character identities are in each member
manifest and the aggregate bundle.

| member | D2 states/transitions/episodes/survival | D3 events/outcomes/summaries | D4A selections/outcomes/comparisons | D4B attempts/available/abstained/outcomes/comparisons/distributions |
|---|---:|---:|---:|---:|
| temporal BTCUSDT 1h | 992 / 494 / 82 / 8 | 39 / 156 / 8 | 78 / 312 / 16 | 2496 / 2432 / 64 / 9728 / 512 / 112 |
| ETHUSDT 1h | 992 / 494 / 80 / 8 | 38 / 152 / 8 | 76 / 304 / 16 | 2432 / 2368 / 64 / 9472 / 512 / 112 |
| SOLUSDT 1h | 992 / 494 / 76 / 8 | 36 / 144 / 8 | 72 / 288 / 16 | 2304 / 2240 / 64 / 8960 / 512 / 112 |
| BTCUSDT 4h | 992 / 494 / 92 / 8 | 44 / 176 / 8 | 88 / 352 / 16 | 2816 / 2752 / 64 / 11008 / 512 / 112 |

Aggregate: 4 fresh replays, 1172 executed prefixes, 992 recorded positions,
2752 stochastic selection attempts, 10752 null outcomes, 2048 D4A outcomes,
2048 D4B repetition comparisons and 448 distribution rows.

## 7. D2 structural summaries

Line and ray summaries are identical per member: 248 eligible points, 247
transitions, active mean/min/max `2.0 / 2 / 2`, zero shape revisions and zero
role switches. Aggregate rates below use summed transition numerators and
denominators.

| member | unit | births | disappearances | persistent | persistence | birth/disappearance | episodes | observed births | survival 1/3/6/12 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| BTCUSDT 1h temporal | line/ray | 39 | 39 | 455 | 0.921053 | 0.078947 | 41 | 39 | 1.000 / 1.000 / 0.811 / 0.343 |
| ETHUSDT 1h | line/ray | 38 | 38 | 456 | 0.923077 | 0.076923 | 40 | 38 | 1.000 / 1.000 / 0.806 / 0.324 |
| SOLUSDT 1h | line/ray | 36 | 36 | 458 | 0.927126 | 0.072874 | 38 | 36 | 1.000 / 1.000 / 0.800 / 0.333 |
| BTCUSDT 4h | line/ray | 44 | 44 | 450 | 0.910931 | 0.089069 | 46 | 44 | 1.000 / 1.000 / 0.744 / 0.238 |

Every D2 bundle retains separate fitted-line and boundary-ray rows, all
states, transitions, drift rows, episodes and survival rows.

## 8. D3 interaction role/horizon summaries

Rows below retain exact counts. Rates are touch, defended-after-touch,
confirmed-break and false-break rates. `R` is right-censored count; `U` is
unresolved-break count. Full rows, including excursions and latency, remain
in each `interaction_utility_bundle.json`.

```text
member/timeframe  role       h  events eligible R  touch defended candidate confirmed false unresolved
BTC 1h temporal   support    1  17     17      0  3/17   2/3      3         0/3       0/3   3
BTC 1h temporal   support    3  17     16      1  5/16   3/5      6         3/6       0/6   3
BTC 1h temporal   support    6  17     16      1  6/16   3/6      8         7/8       1/8   0
BTC 1h temporal   support   12  17     15      2  5/15   2/5      7         6/7       1/7   0
BTC 1h temporal   resistance 1 22     22      0  4/22   2/4      3         0/3       0/3   3
BTC 1h temporal   resistance 3 22     22      0  9/22   3/9      8         3/8       1/8   4
BTC 1h temporal   resistance 6 22     21      1 10/21   3/10     9         5/9       4/9   0
BTC 1h temporal   resistance12 22     20      2 12/20   4/12    10         5/10      5/10  0
ETH 1h           support    1 20     20      0  3/20   1/3      2         0/2       0/2   2
ETH 1h           support    3 20     19      1  9/19   5/9      5         2/5       0/5   3
ETH 1h           support    6 20     19      1 11/19   6/11     8         6/8       0/8   2
ETH 1h           support   12 20     18      2 10/18   5/10     9         9/9       0/9   0
ETH 1h           resistance 1 18     18      0  4/18   2/4      4         0/4       0/4   4
ETH 1h           resistance 3 18     18      0  8/18   3/8      6         3/6       1/6   2
ETH 1h           resistance 6 18     17      1 11/17   5/11    10         5/10      3/10  2
ETH 1h           resistance12 18     16      2 11/16   5/11    11         8/11      2/11  1
SOL 1h           support    1 15     15      0  3/15   2/3      2         0/2       0/2   2
SOL 1h           support    3 15     15      0  5/15   3/5      5         2/5       0/5   3
SOL 1h           support    6 15     15      0  6/15   4/6      7         5/7       0/7   2
SOL 1h           support   12 15     14      1  6/14   5/6      6         6/6       0/6   0
SOL 1h           resistance 1 21     21      0  6/21   2/6      5         0/5       0/5   5
SOL 1h           resistance 3 21     21      0  9/21   4/9      7         4/7       1/7   2
SOL 1h           resistance 6 21     20      1 12/20   4/12    12         8/12      2/12  2
SOL 1h           resistance12 21     19      2 13/19   6/13    14        10/14      4/14  0
BTC 4h           support    1 17     17      0  6/17   4/6      3         3/3       0/3   0
BTC 4h           support    3 17     17      0  8/17   5/8      8         8/8       0/8   0
BTC 4h           support    6 17     17      0 10/17   7/10     9         9/9       0/9   0
BTC 4h           support   12 17     16      1 11/16   8/11    11        11/11      0/11  0
BTC 4h           resistance 1 27     27      0  6/27   2/6      4         4/4       0/4   0
BTC 4h           resistance 3 27     26      1  9/26   4/9      6         6/6       0/6   0
BTC 4h           resistance 6 27     26      1 15/26   7/15    10        10/10      0/10  0
BTC 4h           resistance12 27     26      1 19/26   9/19    16        16/16      0/16  0
```

## 9. D4A comparison rows

Each member has exactly 16 rows: two deterministic baseline kinds × two roles
× four horizons. All selections were available; no D4A abstentions occurred.
The rows contain matched denominators and all seven model-minus-baseline
delta fields. Exact canonical rows are retained at:

```text
members/<member>/deterministic_baseline_comparison_bundle.json
```

| member | recent-extrema selections/outcomes | horizontal selections/outcomes | comparison rows | matched pairs by role/horizon |
|---|---:|---:|---:|---|
| temporal BTCUSDT 1h | 39 / 156 | 39 / 156 | 16 | event count minus right-censored horizons |
| ETHUSDT 1h | 38 / 152 | 38 / 152 | 16 | same exact paired coordinates |
| SOLUSDT 1h | 36 / 144 | 36 / 144 | 16 | same exact paired coordinates |
| BTCUSDT 4h | 44 / 176 | 44 / 176 | 16 | same exact paired coordinates |

No comparison winner or composite score was added.

## 10. D4B distribution summaries

Each member has 112 rows: two stochastic baselines × two roles × four
horizons × seven metrics. Every row has 32 repetitions, with defined and
undefined repetition counts, mean/median/min/max, q05/q95 and sign counts.
Full distribution rows are retained at:

```text
members/<member>/stochastic_null_comparison_bundle.json
```

Touch-rate distribution inventory (`mean / q05 / q95`, with sign counts
`negative / zero / positive`) is shown below; remaining six metrics are in
the canonical bundles.

```text
member       baseline  role        h   mean       q05        q95        signs
BTC1h        random    support     1   0.106618   0.000000   0.176471   0/4/28
BTC1h        random    support     3   0.146484   0.000000   0.278125   0/6/26
BTC1h        random    support     6   0.179688   0.034375   0.312500   1/1/30
BTC1h        random    support    12   0.112500  -0.096667   0.266667   4/1/27
BTC1h        random    resistance  1   0.093750   0.000000   0.181818   0/3/29
BTC1h        random    resistance  3   0.208807   0.136364   0.318182   0/0/32
BTC1h        random    resistance  6   0.232143   0.142857   0.333333   0/0/32
BTC1h        random    resistance 12   0.278125   0.150000   0.372500   0/0/32
BTC1h        density   support     1   0.029297  -0.062500   0.125000   5/9/18
BTC1h        density   support     3  -0.004167  -0.133333   0.133333  11/11/10
BTC1h        density   support     6  -0.070833  -0.266667   0.066667  17/9/6
BTC1h        density   support    12  -0.200893  -0.357143  -0.071429  31/0/1
BTC1h        density   resistance  1  -0.151786  -0.307143  -0.047619  32/0/0
BTC1h        density   resistance  3  -0.078869  -0.238095   0.047619  23/4/5
BTC1h        density   resistance  6  -0.101562  -0.250000   0.022500  23/7/2
BTC1h        density   resistance 12  -0.064145  -0.234211   0.105263  19/7/6
ETH1h        random    support     1   0.098438   0.027500   0.150000   0/2/30
ETH1h        random    support     3   0.335526   0.210526   0.421053   0/0/32
ETH1h        random    support     6   0.378289   0.263158   0.473684   0/0/32
ETH1h        random    support    12   0.302083   0.166667   0.444444   0/0/32
ETH1h        random    resistance  1   0.088542  -0.055556   0.166667   3/3/26
ETH1h        random    resistance  3   0.277778   0.166667   0.388889   0/0/32
ETH1h        random    resistance  6   0.375000   0.208824   0.470588   0/0/32
ETH1h        random    resistance 12   0.394531   0.221875   0.500000   0/0/32
ETH1h        density   support     1  -0.064145  -0.157895   0.023684  22/8/2
ETH1h        density   support     3   0.065972  -0.025000   0.166667   2/5/25
ETH1h        density   support     6   0.024306  -0.111111   0.111111   5/9/18
ETH1h        density   support    12  -0.090074  -0.202941   0.000000  27/4/1
ETH1h        density   resistance  1  -0.196691  -0.320588   0.000000  29/3/0
ETH1h        density   resistance  3  -0.147059  -0.320588   0.000000  29/2/1
ETH1h        density   resistance  6  -0.031250  -0.215625   0.125000  14/11/7
ETH1h        density   resistance 12  -0.112500  -0.200000   0.030000  25/5/2
SOL1h        random    support     1   0.175000   0.133333   0.200000   0/0/32
SOL1h        random    support     3   0.260417   0.170000   0.333333   0/0/32
SOL1h        random    support     6   0.287500   0.200000   0.400000   0/0/32
SOL1h        random    support    12   0.308036   0.142857   0.428571   0/0/32
SOL1h        random    resistance  1   0.165179   0.073810   0.238095   0/0/32
SOL1h        random    resistance  3   0.221726   0.121429   0.307143   0/0/32
SOL1h        random    resistance  6   0.298437   0.177500   0.400000   0/0/32
SOL1h        random    resistance 12   0.343750   0.210526   0.473684   0/0/32
SOL1h        density   support     1   0.017857  -0.071429   0.071429   8/8/16
SOL1h        density   support     3   0.022321  -0.071429   0.142857   8/10/14
SOL1h        density   support     6  -0.089286  -0.214286   0.071429  25/4/3
SOL1h        density   support    12  -0.086538  -0.230769   0.076923  23/6/3
SOL1h        density   resistance  1  -0.079688  -0.222500   0.050000  22/5/5
SOL1h        density   resistance  3  -0.070313  -0.245000   0.122500  21/7/4
SOL1h        density   resistance  6  -0.027961  -0.210526   0.157895  16/9/7
SOL1h        density   resistance 12  -0.036458  -0.191667   0.111111  17/7/8
BTC4h        random    support     1   0.273897   0.176471   0.352941   0/0/32
BTC4h        random    support     3   0.371324   0.267647   0.470588   0/0/32
BTC4h        random    support     6   0.452206   0.352941   0.529412   0/0/32
BTC4h        random    support    12   0.482422   0.312500   0.590625   0/0/32
BTC4h        random    resistance  1   0.126157   0.074074   0.185185   0/0/32
BTC4h        random    resistance  3   0.198317   0.098077   0.269231   0/0/32
BTC4h        random    resistance  6   0.348558   0.251923   0.440385   0/0/32
BTC4h        random    resistance 12   0.427885   0.328846   0.538462   0/0/32
BTC4h        density   support     1   0.037109  -0.090625   0.153125   7/6/19
BTC4h        density   support     3  -0.029297  -0.215625   0.125000  15/10/7
BTC4h        density   support     6  -0.097656  -0.187500   0.028125  28/2/2
BTC4h        density   support    12  -0.127083  -0.200000   0.000000  27/5/0
BTC4h        density   resistance  1  -0.060096  -0.132692   0.038462  24/4/4
BTC4h        density   resistance  3  -0.151250  -0.280000  -0.080000  32/0/0
BTC4h        density   resistance  6  -0.086250  -0.218000   0.040000  25/4/3
BTC4h        density   resistance 12  -0.033750  -0.120000   0.080000  20/5/7
```

This is an evidence inventory, not an adequacy interpretation.

## 11. Artifact and checksum evidence

```text
output root:
artifacts/trendlines_research_robustness/20260727_l2d5b_offline_replication_v1/

robustness_replication_bundle_id:
b0eff1ecd259af4193f70d6ada991a3f7ef0e8731bece95ffd02c15045c7da9b

files in checksum inventory: 23
inventory bytes: 62,643,644
filesystem size: approximately 60 MB
checksums: valid, lowercase SHA-256
```

Four member directories each contain complete D2, D3, D4A and D4B bundles;
full stochastic null outcomes were retained. No D5A source frame was copied.

## 12. Validation

```text
D5B package + script:       41 passed
D5B artifact readback:      passed
D5B required adequacy regression: 278 passed
Canonical mature suite:           731 passed
Viewer Python:              30 passed
Viewer Node/TypeScript:     23 passed
Consumer/ingestion/bridge:  79 passed
Offline workflows:          20 passed
Ruff/compileall/diff-check: passed
Provider calls/retries:     0 / 0
Fresh replay members:       4
Executed prefixes:          1172
Recorded positions:         992
Outcome:                    null
```

Artifact-only readback verified aggregate/member IDs, all nested bundle IDs,
member order and checksum inventory. No provider construction exists in D5B
script paths.

An unrelated existing D2 script test still asserts historical base commit
`b839f5d`; it fails against current D5B base `c503bbe` and no D2 path was
changed. It is outside the D5B-R1 required matrix and was not modified.

## 13. Scope and abstractions

Added one protocol/result-contract module and one thin offline script with
focused tests. No generic workflow engine, registry, manager, repository,
plugin layer, provider path, model change, YAML change, viewer/notebook change,
or D5C/D5D path was added.

## 14. Residual risks and next work

Each member uses one 312-bar window. Evidence remains descriptive and does not
establish robustness beyond these four predeclared cohorts. Event counts differ
by member and are retained rather than normalised away. D4B nulls remain tied
to each member's model-event opportunities. D5C parameter sensitivity and D5D
cross-member synthesis/final disposition are required before any adequacy
decision.

No member is labelled pass/fail.

## 15. R1 protocol-binding remediation

Independent review found that member validation checked internally valid
chains but did not prove that study and null configuration content implemented
the frozen D5B protocol. The validator now binds:

- exact member study window, replay recording bounds and minimum warm-up/prefix;
- metric names/order, empty decision rules, line/ray units, invalid-point
  treatment and causal availability policy;
- deterministic baseline IDs and exact D4A baseline-spec dictionaries;
- D2/D3/D4A/D4B study-config IDs;
- exact D4B stochastic baseline dictionaries, including names, kinds,
  preservation fields, seeds, repetitions, data policy, semantics and IDs;
- exact D4B quantile probabilities.

Focused tests cover each protocol mutation without rerunning official members.
The four member bundles, replay/cohort/study IDs, D2/D3/D4A/D4B IDs, member
result IDs, aggregate ID and all numerical payloads remain unchanged. Official
member bundles were not regenerated. Manifest test disposition and checksum
inventory were refreshed through `finalize_test_disposition()`.

## 16. Required conclusion

D5B applied unchanged causal D2–D4B protocol offline to all four fresh source
members with member-specific YAML-resolved hold-bars. Source, replay and
evidence identities are preserved; provider calls remained zero. The work is
ready for independent robustness review.

`READY_FOR_L2D5B_ROBUSTNESS_REVIEW`
