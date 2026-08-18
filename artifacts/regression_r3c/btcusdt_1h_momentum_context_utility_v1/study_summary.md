# R3C1 BTCUSDT/1h Momentum Context Utility

Status: `STUDY_COMPLETE`

This is a deterministic, point-in-time descriptive study. It does not
select thresholds, define a trading rule, report IID significance, or
recommend a runtime change.

- Source: `src/libs/models/trendlines/optimization/results/BTCUSDT_1h_2022-01-01_2026-03-01.csv`
- Source SHA-256: `3061187fd7092131e7df221fb1c23ea4427ba9754284910d79d47872858c0f66`
- Source rows: `36481`
- Eligible observations: `36297`
- Folds: `development, validation, holdout`
- Horizons: `[1, 2, 4, 8, 16]`

## Fixed descriptive reference points

- Holdout combined directional h=1: n=1398, mean aligned log return=8.067173128701826e-05, continuation rate=0.46494992846924177
- Holdout combined directional h=16: n=1398, mean aligned log return=-0.000354605692670939, continuation rate=0.4642346208869814
- Holdout h=1 region groups observed: `5`
- Holdout h=1 continuous fields with defined Spearman rho: `4/4`

## Integrity

- Bounded Decision history maximum: `136`
- Future-suffix observation unchanged: `True`
- Future label changed under suffix mutation: `True`
- Cumulative runtime manifest: `2085c0f9cf290e763c97b016bb2ea38a2cc22559500d357cf475c2d085b017e0`
- R3P manifest: `93f8c140560e5a5f6237fe4805e309ab07f3fdbcbd77b9bbd33f127d26dce8cc`

No promotion disposition is emitted by this study.
