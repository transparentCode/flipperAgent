# Coder-to-Orchestrator Handoff: L2-D5A Robustness Source Matrix

## 1. Disposition

`READY_FOR_L2D5A_SOURCE_REVIEW`

D5A acquired and froze source evidence only. No model, replay, D2, D3,
D4A, D4B, sensitivity, or adequacy calculation ran on fresh members.
Outcome remains `null`.

## 2. Branch and starting commit

```text
branch: research/trendlines-adequacy-v1
implementation_base_commit: 48fee68acdd2a98256c842e0d1954801a5926293
```

No commit was created during D5A.

## 3. Parallel-main path audit

`origin/main` (`a6fe843a93602af294f7a4d452bb0c9c20d2e119`) was inspected from
common base `29a068a9032b826f88a859623b52faaeedeaee93` without
synchronization. Main-exclusive changes were confined to Trendline V2 viewer
plans, scripts, source, and tests. No overlap existed with mature trendlines,
shared research identity/data code, or D5A paths. No merge or rebase was
performed.

## 4. Frozen source matrix

Five members are bound in this exact order:

| relation | member | asset | timeframe | event start | knowledge cutoff | rows |
| --- | --- | --- | --- | --- | --- | ---: |
| reference | `reference-btcusdt-1h-20250101-v1` | BTCUSDT | 1h | 2025-01-01 00:00Z | 2025-01-13 23:59:59.999Z | 312 |
| temporal | `temporal-btcusdt-1h-20250401-v1` | BTCUSDT | 1h | 2025-04-01 00:00Z | 2025-04-13 23:59:59.999Z | 312 |
| cross_asset | `cross-asset-ethusdt-1h-20250401-v1` | ETHUSDT | 1h | 2025-04-01 00:00Z | 2025-04-13 23:59:59.999Z | 312 |
| cross_asset | `cross-asset-solusdt-1h-20250401-v1` | SOLUSDT | 1h | 2025-04-01 00:00Z | 2025-04-13 23:59:59.999Z | 312 |
| cross_timeframe | `cross-timeframe-btcusdt-4h-20250401-v1` | BTCUSDT | 4h | 2025-04-01 00:00Z | 2025-05-22 23:59:59.999Z | 312 |

Fresh members use equal 312-bar samples. BTCUSDT 4h uses equal bar count,
not equal calendar duration, so later replay scope can remain sample-size
aligned without claiming equal elapsed time.

All members bind `open_time` event semantics and `exchange_close_time`
availability. The reference is bound in place; it is not copied or fetched.

## 5. Acquisition protocol

Fresh acquisition used `BinanceNativeAdapter` through
`BinanceTrendlineResearchLoader` with page limit `1000`, fresh loader per
member, and fixed order:

```text
BTCUSDT 1h temporal
ETHUSDT 1h cross-asset
SOLUSDT 1h cross-asset
BTCUSDT 4h cross-timeframe
```

Results:

```text
provider calls:       4 total; 1 per fresh member
page counts:           1 / 1 / 1 / 1
application retries:   0
model executions:      0
replay executions:     0
```

Failure policy stops on first error, makes no retry, does not call remaining
members, and publishes no official root. The script refuses to overwrite an
existing completed output root and has no force option.

## 6. Reference bindings

```text
reference artifact:
artifacts/trendlines_research_validation/20260726_btcusdt_1h_single_call_v1/normalized_ohlcv_v2.json
reference artifact SHA-256: d6798e34731b4d8978e878c5f7703bdac187eed8c0917efe8f4344768f91c9d1
reference member_spec_id: 0cf10ad5851c1d6fc79cf727cee67ea24933ba9e5add6cf1bd2e1898a36b8482
reference member_evidence_id: 367df5cf9a77209c335da8bccaa1201237032a4eec7f83ed24eec5a0759b7309
reference artifact_id: 60b0d2901e47232cec21bf41be25f17ca18cac080be8eb1f791d0932cd54c8da

source_id:       d3cba96f006b5f7e05a38d888b60b799f128f41567030f0663da908e005f0331
availability_id: 9b3e8f49e408d7781b89a686787e989888d25638683e1a8ab921c1043d4f8bd1
dataset_id:      6464eede955ccfcf0ac023b7b96d026235e6763cbc4eb10470f9c31ee9b0002c
preparation_id:  ff653424e4e848a52666859f14c819c517f79a13d3bc980431bbadc5d15b8141
research_configuration_id:
ab6ec43eede637492f1e11bea6f4ae0cf72ef12045ee87265d648edb0cfc5853
```

Prior evidence chain remained bound:

```text
D2:  f74fcfe1a16c0a3b489aeb61090c861d49c91fc578a31c9217673d8b581d254f
D3:  56d42daeda8bfcfd6625a345c4aef40a9eb9bf63ced415f4a947b9ff546d93a4
D4A: 664a23b5110cea4a3f9370df9d465da3c07c70ceaaae96f29ad8841f31bb7663
D4B: 98f04441c0ef9c643640c78004a875ab6fa6a8de6c797eb1f2e68420910323db
```

## 7. Fresh member evidence

| member | member_spec_id | member_evidence_id | artifact_id | source_id | availability_id | dataset_id | preparation_id |
| --- | --- | --- | --- | --- | --- | --- | --- |
| temporal BTCUSDT 1h | `7cb30d534b6e6ddaef35e4d115ee308bf0ca442e121107ef4f7f919d6078b67f` | `8bab34885f1432a9a59092620bb2b636467894830e7917eddfb3d287a6c60e7b` | `3341e10af426b1e8e559dda871aa79412a14103aee337e2bb93faf8e905bd430` | `1c80f2d3ea463c467ce5f83aba340c4a878d75382f371d59d4453cf85911d059` | `e58847bea0a619da27a4f53dde19830433d201b9556de248a0b0f852aa1dc0e8` | `1e462fc4fb1d79a2d03dc057356a37d4a598b20ec06553b76a5ee1d22d3d8f3b` | `f9700b6f4dba8bc4efb5888ed0737a735eefaf2e526a8526c709563546f51902` |
| cross-asset ETHUSDT 1h | `9bdca6c701807ed0bdccb1e59d86dbd05666c1a1ab5c8939330e096855b4a895` | `c251ec800c5c67b699eb26b4a4816b99c1d064640e46f228e3e09fedd5b6d3d0` | `21f071c7fe297be2d4a79a4902bcdcab57cfe35315fd1e372491624908ff12f6` | `d0e6daec17f5cdcd5ea758b399c2e3eadd40be90138476a5f80b489c63cc17ac` | `d00aae3d3cf1c0a06af004cc00db4377ad83f0ba306f6b7a711dea5b4b4d4a27` | `6ec815da325ae4e5b93335f797c5784eebfa9ac8dcb11f6cdb32a7e35debd582` | `ceee946b076e1c3e924030c9260ee7a1dd440f1d8d39b9bc2c469cb75378069d` |
| cross-asset SOLUSDT 1h | `29e27918ddd2de25f9bebd06bd346935d7e21504347ce88b74bc186c57aec5b6` | `4bb550ccb921c230f6b4c8309e1508d84476456864232f7996389a75501524d3` | `2802700d2d9dc29b17dc43af5966a697d5f976c031b72ca414d5d78895e16f2b` | `ce5da8953f42b5638291ae5ee7d95a20f4937f25c88dc91300c289cf61bd825d` | `d6087914c15b9ac453ea9698d6dd8b059362a990566f9b620587ca132798e31b` | `6304a6573a0fc0071e129d4debf7283dd50ebde27f7f5475fb6badd776f81265` | `4a1b76ca971f9560d28ed5ddad9e66f1bb863c81c413a7261a4a8309d80cd761` |
| cross-timeframe BTCUSDT 4h | `ea5dbc8dc1fa97b1daae20e3773ac668edbda0c7c0e59aa17c61572a4397e709` | `d8ed2c4d12c9097aba8c42c30777fc22ce1f72ad6a898af08818807b0b0772d5` | `a228126cd8067bd7df3132ab47451044516e4531763a5c59522054a0025e337c` | `362b812384cdd357c33f7a15035d59bfb8f0e7ab3f8c0b11cfeb417bb52a8003` | `e23bcb4a2abfad330c955095f1d3f937e83f9b915fd625cfb0d48adb9cf610b8` | `db7d1cfd13274e914793ac4c009e0381f77f81b8e73a8f24c96be65dbd1fa249` | `855474ccfac2c8ed407bbfdc042035a0f579f3c2737a1e629aa4ff993ff7a5cf` |

Each fresh member recorded `provider_calls=1`, `page_count=1`, and 312 rows.

## 8. Round-trip proof

For each fresh member, the acquired frame was written to
`normalized_ohlcv_v2.json`, reloaded through `read_research_frame_artifact()`,
and injected into a second preparation. Exact frame values/dtypes/attributes
and these identities were equal before/after reload:

```text
source_id
availability_id
dataset_id
research_configuration_id
preparation_id
```

Post-acquisition artifact-only readback revalidated all five frame grids,
typed matrix identity, prior evidence bindings, and checksums without any
provider, model, or replay call.

## 9. Published artefacts

```text
root:
artifacts/trendlines_research_robustness/20260727_l2d5a_source_matrix_v1/

robustness_source_matrix_bundle_id:
9e324fff3bfce51eadb86fdcc173d75e984064d7eeaccb3d413fc4c8b13e907a

files:
7 canonical files; approximately 160K total
```

Checksums:

```text
members/cross-asset-ethusdt-1h-20250401-v1/normalized_ohlcv_v2.json
  30355 bytes  62a948668a2cd6a34b0ed785c2280d42f15b5b07d3a8164f372ed6f67ad9c711
members/cross-asset-solusdt-1h-20250401-v1/normalized_ohlcv_v2.json
  30355 bytes  f24621863f6162b7fe331b2bfe508eacfc00a9a7e4ecfa183c9660b875a7b89f
members/cross-timeframe-btcusdt-4h-20250401-v1/normalized_ohlcv_v2.json
  30355 bytes  ae236794baf500e9b849e14ac89c69126a99d5a120251956148b0b8db33cb67d
members/temporal-btcusdt-1h-20250401-v1/normalized_ohlcv_v2.json
  30355 bytes  763637b593f42923eda67fcb1d7a0ed2bf176b7dc55865f24b72a252ba00bd4f
review.md
  615 bytes   82c52afb65d8de01c4478c0e1e41fb643f55a7cd2436c7fbcf6a87ec003d4537
robustness_source_matrix_bundle.json
  8637 bytes  49d22f9c901092ac6ac02c5e0a1a04ac0002bcfceff2871d939cc9ee399d96cc
run_manifest.json
  11246 bytes 9fc12bf93884af38398b7fb28b4f027597c0c132e5b39058362fce1b360829e0
```

`checksums.json` indexes those seven files and was independently verified.
Canonical source-matrix identity excludes paths, wall-clock values, and
durations. Manifest records paths for audit navigation only.

## 10. Validation

```text
D5A focused package:       18 passed
D5A network-free scripts:  18 passed
Canonical mature suite:   699 passed
D4B focused:               52 passed
D4A focused:               40 passed
D3 focused:                52 passed
Viewer Python:             30 passed
Viewer Node/TypeScript:    23 passed
Consumer/ingestion/bridge: 79 passed
Offline workflows:         20 passed
Ruff:                      passed
compileall:                passed
git diff --check:          passed
Repository caches:         removed after validation
```

The four provider calls occurred only during the single official acquisition.
All later validation and readback was offline. No D5B, D5C, or D5D work began.

## 11. Residual risks and next phase

Source acquisition does not establish quality robustness. Fresh members have
not yet received D2-D4B replay or metric execution. Cross-window, cross-asset,
and cross-timeframe conclusions remain unmeasured. Parameter sensitivity is
deferred to D5C. Next authorized phase is D5B: offline reconstruction and
unchanged D2-D4B protocol replication over this frozen source matrix.
