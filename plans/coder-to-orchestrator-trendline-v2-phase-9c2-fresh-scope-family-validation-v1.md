# Coder Handoff: Trendline V2 Phase 9C.2

## 1. Completion

`READY_FOR_ORCHESTRATOR_REVIEW`

Phase 9C.2 physical-horizon remediation is complete. The six original
provider results were retained and all derived evidence was regenerated
offline. No provider or network request was made during remediation. No
runtime, YAML, provider configuration, tracker, MTF, viewer, or model source
was changed.

## 2. Branch and scope

- Branch: `research/trendline-v2-phase-9c2-fresh-scope-family-validation-v1`
- Base: `2d1da900399d9dc9a4d0dc2c9791f668b8b9fb86`
- Changed files:
  - `scripts/analyze_trendline_v2_fresh_scope_family_validation.py`
  - `tests/scripts/test_trendline_v2_fresh_scope_family_validation.py`
  - `plans/coder-to-orchestrator-trendline-v2-phase-9c2-fresh-scope-family-validation-v1.md`
- No commit was created.
- Generated evidence is outside Git at:
  `/tmp/trendline_v2_phase9c2_fresh_scope_family_validation/20260522_20260701/`
- Superseded pre-remediation bundle is preserved byte-for-byte at:
  `/tmp/trendline_v2_phase9c2_fresh_scope_family_validation_superseded/20260522_20260701_pre_physical_horizon_remediation/`

## 3. Frozen identities

- Phase 9C.1 commit: `2d1da900399d9dc9a4d0dc2c9791f668b8b9fb86`
- Cohort contract: `55fabdf05929e923776d810c9958b26c44a8e85a5b92f73ec3027ab92dfcf00a`
- Cohort source: `c8cb7ecb7337020d09b3fe7a3026a14b84d07734252aa9bfa3f563d30f36ae72`
- Source decision: `215600f4b80c356e95e969948dfd12ba57b17a55b140c25a8ea78ad3c9c15424`
- Source manifest: `e2afa4234054396ce5a7343eeb30f0e409fb56f0766c9c11a067180162374d56`
- Source inventory: `631f23915654009fbc5d4fe6adbd5a2b9c300107bc54e6660930c404fc9598be`
- Foundation config: `02cdb171472b8ede327c2466c08ce295d72b16e34367047928757f80fd4f8396`
- Provider config: `2aea7331fad4032db1803f21faa2df42fb2142f365331edce0723db5c55a2e6c`
- Combined config: `7c5c9a8e9513588548145afb085a40d16b7a39738a6a670e0af2613a4bf1d636`
- Provider contract: `13828b02b649fc002681137bae82761d91283e8d1f19d3a3fbd719b8f1cf0e99`
- Selector contract: `1b19f356e186b5fa6ee802e7b738ca06edd7fccdf65c768841911f5a10bc3eb1`

## 4. Provider execution audit

Exactly six successful historical local executions occurred, in the required
order. All had `network_request_count=0`, `retry_count=0`, `fallback_count=0`,
and the fixed provider configuration. No provider result reached a workload
cap. Remediation execution count was `0`; the canonical execution audit binds
the superseded inventory
`c4dde7c52c8c9735af218ee6e53353f312c5c36dea7a1345c0fc7c93b8a3cc20`.

| Order | Dataset | Rows | Candidates | Request identity |
|---:|---|---:|---:|---|
| 1 | `btcusdt_1h` | 960 | 4343 | `16c53b3a36e4d063c15830e3b0131773c07f26e2d87b31e909af3d88f25b67ff` |
| 2 | `btcusdt_4h` | 240 | 673 | `d04efffd43a6cb6ee401c95773f25bd92c2efe1dc489e4c8bd7a674af1961869` |
| 3 | `ethusdt_1h` | 960 | 4264 | `bb57b0b97e9f04fb658bfc51e5b2efdf89763c503a40921ec2bb1020d0925fa5` |
| 4 | `ethusdt_4h` | 240 | 721 | `e9a9d46c9296b2b63ff02fd072400e79e6d1bd9ef16a93698d162ab2187db18f` |
| 5 | `suiusdt_1h` | 960 | 4410 | `923f2c89cce0adb0a45069542b26447e167679b90624654e6c4e431f75a2de60` |
| 6 | `suiusdt_4h` | 240 | 876 | `6f75f29b8325e23bef6d055ad0eb6ad1c1ac6e7c09401986378065b698ba95ea` |

Role counts (support/resistance): `BTC 1h 2112/2231`, `BTC 4h 373/300`,
`ETH 1h 2246/2018`, `ETH 4h 402/319`, `SUI 1h 1978/2432`, `SUI 4h 425/451`.

## 5. Physical horizons

The authoritative `HORIZON_BARS_BY_TIMEFRAME` mapping is `1h: 24/48/96`
and `4h: 6/12/24` bars for `24h/48h/96h`. Every persisted evaluation includes
`horizon` and `horizon_bars`. Future labels begin at
`max(confirmation_positions)+1` and use exact candle contact and exact
support/resistance body-side violation only.

## 6. Family population

| Dataset | F0 control | F1 adjacent | F2 skip<=1 | F3 skip<=3 | F4 latest | F5 earliest | F6 clearance | F7 prominence |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC 1h | 4343 | 415 | 717 | 1153 | 422 | 422 | 422 | 422 |
| BTC 4h | 673 | 101 | 178 | 284 | 106 | 106 | 106 | 106 |
| ETH 1h | 4264 | 426 | 755 | 1224 | 433 | 433 | 433 | 433 |
| ETH 4h | 721 | 108 | 189 | 305 | 109 | 109 | 109 | 109 |
| SUI 1h | 4410 | 425 | 750 | 1204 | 437 | 437 | 437 | 437 |
| SUI 4h | 876 | 110 | 192 | 311 | 112 | 112 | 112 | 112 |

The locked winner `latest_valid_predecessor_v1` had coverage `1.0` on every
dataset. Its validation candidate fractions were `0.0972`, `0.1575`,
`0.1015`, and `0.1512`; finite-overlap p95 values were `3/4/3/4` and
admission-burst p95 values were `1/1/1/2` for BTC 1h/BTC 4h/ETH 1h/ETH 4h.

## 7. Validation ranking and holdout

Validation-eligible families, in deterministic ranking order:

1. `latest_valid_predecessor_v1`
2. `max_minimum_body_clearance_v1`
3. `max_minimum_anchor_prominence_v1`
4. `skip_le_1_v1`
5. `adjacent_extrema_only_v1`

`skip_le_3_v1` failed the candidate-fraction gate on the validation scope;
F0 is the control and cannot qualify as a reduction family. The lock was
written before SUI execution and no family was changed after SUI results.

The locked winner passed both holdout datasets. Winner group-weighted deltas
(survival / contact-and-survival) were:

- SUI 1h: `24h +0.1262/+0.0002`, `48h +0.1562/+0.0042`, `96h +0.1704/+0.0121`.
- SUI 4h: `24h +0.1040/-0.0031`, `48h +0.1293/+0.0341`, `96h +0.1064/-0.0019`.

Final research classification: `FRESH_SCOPE_PROMOTION_CANDIDATE`.
This is not runtime promotion.

## 8. Artifact identities

- Decision ID: `4b734cbf99e1453bccdedb95f397f4b34e020f29e3d18808a131456647f78f7c`
- Decision SHA-256: `df41894e6deab18e9f002533373deb8b4cc7591f0074cb0a48fe5c06c59b6677`
- Validation lock ID: `bde41bd0a4bf14c5677583a378fd3fd9a3c6a161effbaadf7285528ccf780bd6`
- Validation lock SHA-256: `16c73f2bc61a9efa495877cbaec580a2c3f28b40daf93d08adde9b027669723b`
- Manifest ID: `beab5b9acb2bfc3c25ba9cb5cb31c33c1a31e6069c1d7906f3ed5e1c2d798c81`
- Manifest SHA-256: `4db6402a4fdd911cbe8a1b4b30f8ee27431e2f2c751a572d1fec92f0b7d25121`
- Bundle: 38 files, manifest binds 37 data members.

Provider-result IDs, in execution order:

`68975843daddef910a08e390f475fdfc20fe784637767c92f4b1ff7d7cd12f9e`,
`ea53abf260b3b19966140bcb1157c4924b14c43d69307917e59fd95c8f973824`,
`b028dd306fd2131c2752f348847c65c3212060e9eb0b80e637bc84f021a66b77`,
`eaf1f8046f53c1316d7b3d99d5f039698c2d2f02ee7aa467d3fbf37e88dd33ca`,
`e00fd1762260dbcd3f58b327599fc06e09a8b0a43d39c09d29864dcd739f9e0f`,
`0f9b709398b4dfbdf3e078bc041e413afb88590defb09fe6a7f9efb1722734f8`.

## 9. Verification and regression evidence

- Focused hermetic: `24 passed, 6 skipped`.
- Opt-in external bundle verification and copied-bundle adversarial tests:
  `30 passed`.
- Trendline V2 and viewer: `135 passed`.
- Protected Trendline Family: `400 passed`.
- Provider benchmark harness: `4 passed`.
- Frontend build/tests: `13 passed`; `npm audit` reported zero vulnerabilities.
- Ruff, compileall, and `git diff --check`: passed.
- Independent verifier reconstructed every provider result, candidate record,
  family membership, family metric, CSV summary, validation gate/ranking,
  validation lock, holdout, study contract, source audit, execution audit,
  measured stability summary, decision, and manifest without provider or
  network execution.
- Frozen Phase 9C.1 source remained 23 files with inventory
  `631f23915654009fbc5d4fe6adbd5a2b9c300107bc54e6660930c404fc9598be` before
  and after the study.
- Superseded pre-remediation bundle remained 38 files with inventory
  `c4dde7c52c8c9735af218ee6e53353f312c5c36dea7a1345c0fc7c93b8a3cc20`.
- Canonical regenerated bundle is 38 files with inventory
  `ed2eba9415a0e035560cb2f48dc9c0581ec758f9ffabcb629793ba6bca69e532`.

## 10. Codebase memory and limitations

The requested codebase-memory reindex was retried with moderate mode after
remediation. The worker again crashed on a file and reported a contained
failure; no index was replaced. Existing non-zero indexes remain available but
do not constitute a refreshed index for these uncommitted files.

The evidence is descriptive, candidate-weighted and group-weighted; candidates
share anchors and overlapping geometry. The classification concerns one fixed
provider configuration and exact-side continuation evidence only. It is not
evidence of profitability, statistical independence, production readiness, or
canonical provider-parameter adequacy. No runtime filter or configuration was
promoted, and Phase 9D must not begin automatically.
