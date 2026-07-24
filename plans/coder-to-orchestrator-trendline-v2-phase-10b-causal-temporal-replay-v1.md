# Trendline V2 Phase 10B Causal Temporal Replay

Status: `READY_FOR_ORCHESTRATOR_REVIEW`

## Scope

- Branch: `research/trendline-v2-phase-10b-causal-temporal-replay-v1`
- Base: `c2210d00d96701e07d28024613113a7d6d13e2d5`
- Commit, merge and push: not performed.
- Exactly three authorized files:
  - [replay script](/Users/aloobhujia/flipperAgent/scripts/replay_trendline_v2_causal_temporal_tracking.py)
  - [replay tests](/Users/aloobhujia/flipperAgent/tests/scripts/test_trendline_v2_causal_temporal_tracking.py)
  - this handoff
- No `src/` files or provider, selection, tracking, YAML, viewer, runtime, MTF, interaction, event, storage or legacy Trendline Family files changed.

## Checkpoint Contract

- Namespace: `trendline_v2_phase_10b_checkpoint_contract`
- Contract ID: `01e38027a396a03730bccf6479d4cc4ece4a4391d35b32fa13ce94aef01d22b5`
- Identity is the deterministic hash of the canonical payload containing
  `schema_version`, boundary rule, `observed_at == confirmed_through`,
  checkpoint alignment, dataset-major order and every checkpoint date/row
  pair. The payload is persisted under `identity_payload` in
  `study_contract.json`.
- Checkpoints: `2026-06-03`, `06-07`, `06-11`, `06-15`, `06-19`, `06-23`, `06-27`, `2026-07-01` UTC.
- 1h rows: `288, 384, 480, 576, 672, 768, 864, 960`.
- 4h rows: `72, 96, 120, 144, 168, 192, 216, 240`.
- Prefix rule: source timestamp `< checkpoint`; `observed_at == confirmed_through == checkpoint`.
- Dataset-major order: BTCUSDT 1h, BTCUSDT 4h, ETHUSDT 1h, ETHUSDT 4h, SUIUSDT 1h, SUIUSDT 4h.

## Frozen References

| Root | Commit | Decision | Manifest | Inventory | Files |
|---|---|---|---|---|---:|
| Phase 9C.1 source | `2d1da900399d9dc9a4d0dc2c9791f668b8b9fb86` | `215600f4b80c356e95e969948dfd12ba57b17a55b140c25a8ea78ad3c9c15424` | `e2afa4234054396ce5a7343eeb30f0e409fb56f0766c9c11a067180162374d56` | `631f23915654009fbc5d4fe6adbd5a2b9c300107bc54e6660930c404fc9598be` | 23 |
| Phase 9D selection | `722109c5ed86e5d3974e0b2f7fb0d7a637da7a4f` | `c7daee89ffe745e12d4c8dcad65fc27a9c19f7da3b460acc32360af0f814b6cd` | `51fb6ff236e8e6f94d47082c00fa27dc5692ab8e629e0a10959f35ccc2675585` | `aca26bb086c3cd0b8ce04c152ab1b71fa240068c92c8f5691a7848fe3900ecb8` | 11 |
| Phase 10A tracking | `c2210d00d96701e07d28024613113a7d6d13e2d5` | `44fe6f1c0c86563416f023c1c7530be61f30b0755ccf5335fbe0a4086df9ff0f` | `064a641c797c655d2726a4d332168cd3740159790dff1129047ca8bd12979d6a` | `bc560cda8f4cd478313b8e4fb84338dc332679940ba6a56fde7b50dc97415080` | 11 |

All three inventories matched before execution, before publication and during offline verification.

## Fixed Configuration

- Foundation: `02cdb171472b8ede327c2466c08ce295d72b16e34367047928757f80fd4f8396`
- Provider: `2aea7331fad4032db1803f21faa2df42fb2142f365331edce0723db5c55a2e6c`
- Combined: `7c5c9a8e9513588548145afb085a40d16b7a39738a6a670e0af2613a4bf1d636`
- Provider contract: `13828b02b649fc002681137bae82761d91283e8d1f19d3a3fbd719b8f1cf0e99`
- Selection policy: `3213d919e3e325b99ce156272759a42799bf296545b95c338ea803c087f99afc`
- Tracking policy: `82c026cadb53acd15f78e61e4773ff836574802dd0b82f130a80af32ee9353ce`
- Provider values: lookback `10,540,800`; confirmation `1/1`; minimum extrema `2`; max hypotheses `100,000`; max output candidates `10,000`.
- Exactly one configuration variant; no retry, fallback, parallel execution or network.

## Replay Evidence

- Output: `/tmp/trendline_v2_phase10b_causal_temporal_replay/20260603_20260701`
- The original single authorized provider-executing run completed exactly `48` local calls. All outcomes were `SUCCESS`, `reason=null`, one execution, and nonzero in-scope candidate count.
- The corrected bundle was republished offline from the superseded checkpoint
  rows. The remediation made `0` provider executions and `0` network requests;
  no Binance adapter or evaluator was invoked.
- The complete ordered 48-row evidence table, including every prefix identity, provider-result ID, discovery ID, selection ID, tracking ID, candidate count, selected count, active count, birth count, continuation count and removal count, is persisted in `provider_execution_audit.json` plus the 48 checkpoint JSONs. `EXPECTED_EXTERNAL_ROWS` in the test is an exact static copy of all rows and is compared field-for-field.
- The superseded pre-remediation bundle is retained at
  `/tmp/trendline_v2_phase10b_causal_temporal_replay_superseded/20260603_20260701_pre_checkpoint_identity_remediation` with its original 55-file inventory unchanged.
- All 52 non-top-level evidence files in the corrected bundle are byte-identical to the superseded bundle; only `study_contract.json`, `decision.json` and `manifest.json` changed for the corrected provenance identity.

Final provider-result IDs:

| Dataset | Provider result | Selection snapshot | Final tracking snapshot |
|---|---|---|---|
| BTCUSDT 1h | `68975843daddef910a08e390f475fdfc20fe784637767c92f4b1ff7d7cd12f9e` | `ed7959f4591e749f087d5dbb83c74df2a31125c51c2c77303068553e2f1190ab` | `ccca082b51b88e23671b120eec5161232074d9135a5f2fb6142da8094906c763` |
| BTCUSDT 4h | `ea53abf260b3b19966140bcb1157c4924b14c43d69307917e59fd95c8f973824` | `31330b3c58cb0ee8f33979683c080bc881d2d04b8ea76bbe18cacbdce2eb67da` | `64a74c3172d616015a35d924a4a89c31de0784ba7ce44c9609ec66352497dd6b` |
| ETHUSDT 1h | `b028dd306fd2131c2752f348847c65c3212060e9eb0b80e637bc84f021a66b77` | `7178dedceef1b0c97b99777a40b07dad808942330902edd093f83d9cd1ec812b` | `1aa785612831815e9be0973829e76c6fe917d3ed39b0c91308018a5cc3052c02` |
| ETHUSDT 4h | `eaf1f8046f53c1316d7b3d99d5f039698c2d2f02ee7aa467d3fbf37e88dd33ca` | `f9c48aec092b623b89175e56888f88049fb652d75c62da56005d044a16070f56` | `ca731a982f856408f374b189927e83ac5e69c3c1d60109e7f04b7ec761ece57c` |
| SUIUSDT 1h | `e00fd1762260dbcd3f58b327599fc06e09a8b0a43d39c09d29864dcd739f9e0f` | `d2a762fb7ff6c6e1dba2df9fdba877a00511678634c36cab7f75213ac02702db` | `018dc6f9219745a338a6b36b1fb4785a78c02ca18caef9c82880169f34274661` |
| SUIUSDT 4h | `0f9b709398b4dfbdf3e078bc041e413afb88590defb09fe6a7f9efb1722734f8` | `c2175d14d052f8893612508e5c23a66c60322d824191873e6a521da830909b6b` | `86c969fb59ee22b7f2d3b28d8814a4a1c7ebae9ae2c01c64c7d0d18633d71b0c` |

Aggregate decision:

- `EXACT_TEMPORAL_REPLAY_VERIFIED`
- datasets/checkpoints/records: `6 / 8 / 48`
- provider/network/retry/fallback/config variants: `48 / 0 / 0 / 0 / 0`
- provider successes: `48`; unavailable: `0`; source removals: `0`
- final active families: `1,619`; births: `1,619`; continuations: `6,704`; candidate-ID turnover: `6,704`
- active-family checkpoint summary: minimum `26`, median `116.5`, maximum `437`
- final Phase 9D selection parity: `true`; final Phase 10A family parity: `true`

Per-dataset final counts:

| Dataset | Initial active | Final active | Births | Continuations | Final version distribution |
|---|---:|---:|---:|---:|---|
| BTCUSDT 1h | 121 | 422 | 422 | 1,741 | `{1:49, 2:40, 3:42, 4:38, 5:48, 6:40, 7:44, 8:121}` |
| BTCUSDT 4h | 26 | 106 | 106 | 426 | `{1:10, 2:10, 3:12, 4:13, 5:14, 6:11, 7:10, 8:26}` |
| ETHUSDT 1h | 131 | 433 | 433 | 1,810 | `{1:50, 2:36, 3:44, 4:40, 5:50, 6:43, 7:39, 8:131}` |
| ETHUSDT 4h | 28 | 109 | 109 | 433 | `{1:11, 2:11, 3:14, 4:12, 5:12, 6:12, 7:9, 8:28}` |
| SUIUSDT 1h | 135 | 437 | 437 | 1,859 | `{1:50, 2:37, 3:41, 4:38, 5:45, 6:45, 7:46, 8:135}` |
| SUIUSDT 4h | 27 | 112 | 112 | 435 | `{1:12, 2:15, 3:13, 4:9, 5:12, 6:14, 7:10, 8:27}` |

## Artifact Identity

- Decision ID: `0b56ce796076cc6ff0f5f1dda962e3774e704915e82700e52c80103f983de4d7`
- Manifest ID: `5b4aabc2327fc0d37ba925a0fde7207072997edf517814d0db03e05442386927`
- Complete 55-file output inventory SHA-256: `f8fc8e223c3a7e9475e0c3fbcb8a9bf53f75cca678e589aee087eae213ad99dc`
- Superseded 55-file output inventory SHA-256: `2bfbb333a25bf32bd2e2f79fe80ee9dcdb8b096562aafdc70c49a4d21fa91818`
- 48 checkpoint files plus 7 top-level files; manifest binds 54 members.
- Complete path/size/SHA inventory is the `members` array in `/tmp/.../manifest.json`; the external test validates the manifest and output inventory read-only.

## Validation

- Focused replay/tracking: `19 passed, 1 skipped`.
- External exact evidence: `20 passed` in `636.31s`; provider/network during verification `0/0`.
- Trendline V2 models: `192 passed`; protected Trendline Family: `400 passed`.
- Provider benchmark harness: `4 passed`.
- Protected V2/viewer: `215 passed`.
- Frontend: `13 passed`; `npm audit`: `0 vulnerabilities`.
- Ruff, compileall and `git diff --check`: passed.
- Codebase-memory reindex: source `22,716/118,051`; tests `5,533/23,253`;
  scripts `1,402/6,276`; plans `5,257/5,242`; conductor `196/981`; all
  nonzero.
- GitNexus reindex: `49,053 nodes / 81,428 edges`; its stored branch metadata
  remains stale and is not approval evidence.
- GitNexus reindex: `49,023 nodes / 81,368 edges`; branch metadata remains stale at `feature/trendline-v2-phase-10a-tracking-foundation-v1` and is not approval evidence.

## Boundaries and Limitations

- No network request, adapter import, retry, fallback, alternate configuration or parallel execution.
- No approximate matching, ATR/distance matching, confidence/ranking, interaction/event/role-reversal/MTF/storage/viewer/runtime work.
- Evidence is causal exact-lineage evidence only; no profitability, predictive, market-quality or production-readiness claim.
- Phase 10C long-horizon lookback-eviction replay remains unauthorized.

## Review Status

`READY_FOR_ORCHESTRATOR_REVIEW`
