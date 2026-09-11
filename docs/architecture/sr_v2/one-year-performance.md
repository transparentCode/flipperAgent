# One-year bounded execution evidence

Status: `IMPLEMENTED BASE / RESEARCH ONLY` · scientific result:
`INCONCLUSIVE` · promotion: `RESEARCH_ONLY / NO_PROMOTION`.

This is a bounded, ad-hoc determinism and resource receipt. It is not a
benchmark, efficacy result, promotion gate, or production-cache claim.

## Source and provenance

- Asset/instrument: `BTCUSDT` on `binance_usdm`.
- Authenticated source: `.cache/sr_v2_research/BTCUSDT_15m_v2_26b69a399a573a8812fa0c89.jsonl`
- Source bytes: `19,311,834`.
- Source SHA-256:
  `30a1cef7d33bc13bdb859dec1bc4c58652df8a93f8addae15c88544830de8140`
- Source records: `43,701` 15-minute bars, from
  `2025-06-01T07:00:00+00:00` through `2026-08-30T12:15:00+00:00`.
- Manifest:
  `.cache/sr_v2_research/BTCUSDT_15m_v2_26b69a399a573a8812fa0c89.jsonl.manifest.json`
- Manifest bytes: `965`.
- Manifest file SHA-256:
  `520379b446101a0daa4544f280e00db32e7b5fa3cc7ab5c698cdd9ea843c155c`
- Manifest evidence SHA-256:
  `b2e837bd036440f657824b1af998dc742d697d6d2214aac7f2ba637851551c7b`
- Manifest ID:
  `3cf82c747a5be9291c6af5641f8f866f42ec482f464c684c7de88731c0c29bb9`
- Manifest acquisition cutoff: `2026-08-30T12:28:38.321627+00:00`.

The cache is authenticated only at 15m. Complete UTC-aligned 30m, 1h, 4h,
6h, and 1d bars were formed in memory from the 15m records for this command;
they were not written back, treated as independent authenticated lanes, or
promoted into a production resampler/cache.

## Method

The command loaded the cache in `CACHE_ONLY` mode, checked contiguous source
grids, and formed only complete UTC buckets for the configured higher lanes.
It discovered the first cutoff with the configured exact history, then ran
`OfflineCompute` in `GENESIS_EXACT` mode over closed trigger cutoffs. The
model and replay loop were not changed for this receipt. The final state was
encoded with `encode_state` and hashed with SHA-256. The command was run twice
from the same source and configuration.

The configured analysis window is one year:

- analysis start: `2025-08-30T12:15:00+00:00`
- final closed cutoff / knowledge cutoff:
  `2026-08-30T12:15:00+00:00`
- exact analysis window: `365.0` days
- first valid exact genesis cutoff: `2025-06-23T00:00:00+00:00`
- modeled source span including warmup: `433.510417` days
- required history per lane: `21` bars
- configured ladder: `1d → 6h → 4h → 1h → 30m → 15m`
- resolved config fingerprint:
  `2c0de5430e079fc10926ac51a8756c422ccb778bd43f786f40655ef6f273b4c2`

## Two repeated runs

| measurement | run 1 | run 2 |
| --- | ---: | ---: |
| elapsed seconds | `200.27558` | `199.93631` |
| total steps | `41,618` | `41,618` |
| analysis steps | `35,041` | `35,041` |
| final generation | `41,618` | `41,618` |
| final state bytes | `978,570` | `978,570` |
| final state SHA-256 | `b968c8e06947f53692de3b1fd4ee278cf529ac8a0e6602cd1b5fb0b5d4db7e29` | same |
| peak RSS | `166.859 MiB` | `169.219 MiB` |

Peak RSS was measured with
`resource.getrusage(RUSAGE_SELF).ru_maxrss` (macOS reports bytes). The small
RSS difference is process/runtime noise; the encoded state bytes and hash are
identical.

### Input counts

| lane | source/derived bars |
| --- | ---: |
| 15m authenticated | `43,701` |
| 30m in-memory derived | `21,850` |
| 1h in-memory derived | `10,925` |
| 4h in-memory derived | `2,731` |
| 6h in-memory derived | `1,820` |
| 1d in-memory derived | `454` |

### State bounds observed

- maximum active lineages: `470` (configured bound `512`)
- maximum terminal tombstones: `512` (configured bound `512`)
- maximum observed total of these two bounded collections: `982`
- no bound was raised or tuned for this run

## Limitations and residual risks

The cache begins at `07:00Z`, so the first exact daily history cutoff is
`2025-06-23`; this is a valid warmup boundary, not evidence of a complete
pre-history. Higher-timeframe inputs are derived fixtures from one authenticated
15m lane, not six independently authenticated source lanes. No live database,
network source, persistent checkpoint, intrabar path, core/live/checkpoint
probability or calibration output, authenticated production
calibrator/predictor/optimizer, Decision consumer, or MTF fusion was exercised.
Existing research-only scoring scaffolding is gated and non-promoted. The receipt proves
repeatability and observed resource behavior for this bounded fixture only; it
does not establish S/R predictive validity or justify promotion.
