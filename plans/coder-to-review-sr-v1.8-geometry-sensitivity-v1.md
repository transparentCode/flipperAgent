---
goal: Deliver the SR-V1.8 geometry-sensitivity implementation and deterministic development evidence for review
stage: coder-to-review
date_created: 2026-07-16
last_updated: 2026-07-16
owner: Codex
status: Ready
tags: [handoff, quant, sr, v1.8, geometry-sensitivity]
source_agent: Codex quant-coder
target_agent: Quant Review / Orchestrator
---

# SR-V1.8 Geometry Sensitivity

## Scope Executed

Implemented the approved V1.8 development-only 3x3 geometry sensitivity study
for the frozen Binance USD-M TAOUSDT/BTCUSDT/ETHUSDT/SOLUSDT 1d cohort.
The implementation is on:

- branch: feature/sr-v1.8-geometry-sensitivity
- V1.7 authorization/base: f8ecb2437f7f60a1da2ab496f7d8f9807d770d1f
- V1.7 parent: 625878b26faa1cccb330af0e1c7062e3e3f4b1b6
- implementation commit: fa819418aa35b7f325c7a6bf2a51a387aa97f60f

The branch remains unmerged. Two identical evaluations were run after the
hardening commit. This documentation update was made after evidence generation;
no evaluation was rerun after this document was written.

The study consumes the already-published V1.7 source and evaluation bundles
directly. It does not contact Binance, prepare a new source capsule, create or
score a holdout, change production SR behavior, or promote a challenger.

## Changes Made

### Additive implementation

Added:

- configs/sr_trials/sr_v1_8_1d_geometry_sensitivity.yaml
- src/libs/models/sr/scripts/geometry_sensitivity/__init__.py
- src/libs/models/sr/scripts/geometry_sensitivity/config.py
- src/libs/models/sr/scripts/geometry_sensitivity/contracts.py
- src/libs/models/sr/scripts/geometry_sensitivity/candidate_grid.py
- src/libs/models/sr/scripts/geometry_sensitivity/selection.py
- src/libs/models/sr/scripts/geometry_sensitivity/runner.py
- src/libs/models/sr/scripts/geometry_sensitivity/artifacts.py
- src/libs/models/sr/scripts/geometry_sensitivity/cli.py
- tests/models/sr/scripts/geometry_sensitivity/__init__.py
- tests/models/sr/scripts/geometry_sensitivity/conftest.py
- tests/models/sr/scripts/geometry_sensitivity/test_config_grid.py
- tests/models/sr/scripts/geometry_sensitivity/test_selection.py
- tests/models/sr/scripts/geometry_sensitivity/test_artifacts.py
- tests/models/sr/scripts/geometry_sensitivity/test_import_boundaries.py

The package:

- validates the strict, duplicate-safe V1.8 YAML protocol;
- constructs exactly the approved 3x3 candidate grid;
- varies only detection.pivot_span_bars and detection.zone_half_width_atr;
- inherits the other six SR parameters and ATR(14) without hidden fallbacks;
- reuses the approved V1.7 causal replay and cohort aggregation paths;
- checks V1.7 source/evaluation identities and baseline semantic parity before
  evaluating challengers;
- evaluates every candidate independently per asset;
- applies aggregate eligibility, quality, guardrail, and stability gates;
- excludes diagnostic fold gates from promotion while rejecting unknown gate
  categories fail-closed;
- enforces the exact immutable approved V1.8 selection-threshold payload;
- emits deterministic, duplicate-safe study and manifest artifacts;
- exposes only evaluate and validate CLI commands.

No existing V1.7, production, provider, adapter, viewer, runtime, or holdout
module was modified.

### Frozen protocol

| Item | Frozen value |
|---|---|
| ATR | Wilder RMA, period 14, SMA seed, common warm-up 28 |
| Outcome rule | offset 1, horizon 10, half-open UTC daily window |
| Folds | 2024_q3, 2024_q4, 2025_q1, 2025_q2, 2025_q3, 2025_q4 |
| Candidate grid | pivot span 3/5/7 x width 0.15/0.25/0.35 ATR |
| Baseline | pivot span 5, width 0.25 ATR |
| Eligible fold gate | at least 4 completed touches |
| Asset sample gates | at least 4 eligible folds and at least 24 completed touches |
| Comparable cohort gates | at least 4 folds per asset and at least 16 asset-fold units |
| Quality gates | median asset delta 0.10, micro delta 0.10, at least 3 positive assets, worst asset delta -0.10, fold win fraction 0.60 |
| Guardrails | invalidation delta 0.05, density ratio 0.5..2.0, churn delta 0.10, right-censor delta 0.10 |
| Stability gate | at least one fully evaluable improving orthogonal neighbor |

The exact six fold boundaries, gate values, candidate set, and frozen input
bindings are locked in the trial YAML and validated on load.

### Frozen input identities

| Input | Identity |
|---|---|
| V1.7 source bundle | 6b5a0a81117ba299516fb67ca2da81b3cb6e6f35ed6a85986a27689205a565d9 |
| Source path | research/tmp_sr_v1_7/source/6b5a0a81117ba299516fb67ca2da81b3cb6e6f35ed6a85986a27689205a565d9 |
| Source preparation commit | be6459a8e06ec95b634b2cfb2b91a08cd31d9ba2 |
| V1.7 evaluation bundle | 824e9265a63073ba792762a891adf52deec9677d791c40641dc0107c1f2b840d |
| V1.7 evaluation ID | 49a895360774ec0c46349eae2d1ec6f56e7262e5f1411ab992f9886d9040fa8d |
| V1.7 evaluation implementation commit | 4cb069af6142dbd7dadf7a5ebef49d2da0ba26a7 |
| V1.7 config hash | 370d2b66e8e3031b0df8547e8b52c61288e14c5d1b858612ce9fae712e1690a7 |
| Frozen production SR hash | cb9b4143921de95c5423899a5655fef0b186cf1f8e9a84c69427bf64df030299 |
| Frozen input hash | 5ece92803341696df06efa0dba5d7a44ee0f5451aa3ce6555d3a4ef6c59fab6d |
| V1.8 config hash | 86137d2c5b5e12802a5731298ab548822f23c4937d635bae5f21b77a8e7c0da7 |

The V1.8 config also binds configs/sr.yaml and configs/sr_inputs.yaml, the
V1.7 config/evaluation/source identities above, and the frozen SR/input hashes.

### Candidate identities and effective configuration hashes

Candidate IDs are derived from the exact schema-versioned geometry payload.
The four effective hashes are ordered TAOUSDT, BTCUSDT, ETHUSDT, SOLUSDT.

| Geometry | Candidate ID | TAOUSDT | BTCUSDT | ETHUSDT | SOLUSDT |
|---|---|---|---|---|---|
| 3 / 0.15 | 279bd56f8ca051ef403b8de12857d04ac3aa6127fe9617c0ecb9516de7e12d6e | 017a5d16fb0c4f7a51a516e692fa897c8a06ce8226d5df6dc68bd25c709ba2e3 | 387476faafd872a404f07f3f4bf3fbf271bfdf06b8a0a04a13fa8813d1803e80 | 3b6b67f20d12404fe10e4f989730355f37973f91eddba7f7ab88829b01ee6ec9 | 0cde103e54503109833e155cdbf999d39a00447c87793cb054d66135ea3a863f |
| 3 / 0.25 | ccfbec1a8166279f728a1073eb6c1001df4845c0575c3a221c5392951377b434 | 0c59d76ef1ba1b6a8a4354ffa80e9dbf8f50865a4fe76cf54eb7ea142b6a427e | b9aedfa1484f073d3b64c4dc7af562ff1041bbad1da48f1d489d3de3ebbb7774 | 1c47ddb3164cbc35da2adcabe4412afefb2eaca573edb1f62ab53127a62e09d4 | e9729e2ac0d4237d5ad22b30162bdc6d3a7cef80f21923ba8da78f81bc8b2321 |
| 3 / 0.35 | be84c1f446bd4f948d1d991cc80f9a52451b639e4058799bdb7fc5233c7c7f7d | 4a9c63b383eff41f277c1ed17c1a48020a28c202383856ac1d1e5b3a5f06ee86 | e72070c9a53308f98e91a5fce70ee18f0778c2dcbc7bca360f01d6d4bd24448b | d8409cfa39e27e3d4a95a42c109386b2e59e2961d8ca76685553771043cc8a7b | 769ac7ffb5a47f541dfa951a1c4983f9d37572b056b49e82f8696e4452d2fa5d |
| 5 / 0.15 | c039f323b0c1157ebd82fa0b0c82a7a06fe4790e4295a4e0bdfcc4ef7a64f87e | ff62079a0b26dc0fc6374847ff7375ae51e292a28ce67911d19a40aa8c129d14 | f97c272bca5562602af8fe18a70834aaf991a6a01c8658a436a751d76bc578f9 | 21567d69619fbf314032993e9227a1179b63e14d8cc63f15edc52e8b07bfadf6 | 05d24e46ee5938fb2189b1b62f582aad3eea0ffac72c16fb6c8abd377eafb7e5 |
| 5 / 0.25 baseline | 37769b33cc663e4baf5488001252a996b9cb2ec67d0182400f12cb928015709c | cb9b4143921de95c5423899a5655fef0b186cf1f8e9a84c69427bf64df030299 | 7f2d9367983598d6b3cb153ff593adab213ed9bac0bc8441fb72a65e9d555e3f | f2a5d88d933aae6bd3a3fdd3a7baa5f2cc9557a0776e5bae0fe3a3d620ac4f38 | f4d244b3503c4f0f308b506131351d44d3541452ab940384ce37c88e70991c6d |
| 5 / 0.35 | 2c3cea9c1162a089bfd8ef711aee1c9a853610521a727aa9ea1429f63f2c5606 | 059727ee921d229e17756c3deca8f7e7820d156865ea9b15b26f6674926dbf80 | 74fea1f655e734aef1dc21d1c8e618b04af0d96659c64c307bceb226eb502eb7 | 8bff4f72cf257bc0c56d3dc6e0bf5747d515dc11e41f2eb65f2f4682484d0d33 | 1b10a02ff3a7d35f8db4767a06e0f8417fd2483713589b41f59bc6fdaf3cdc7f |
| 7 / 0.15 | 10532c3a67c784cf6bf0247c2cbba04e04b36c581da08facd083785583c4b5d0 | 5a11d3261ed256310c38e0ed7cdca4f26928999473959d7c83cda63abd45f8e1 | a7f9f011764cd3db7b9e4545413340f97b5bdc986abf5aaf6421c24bc0cf3857 | 87826f46f61f25bf1c3194a4cfc47c92f715156845e8fb08a9b2dfed31ba2f58 | 5bf7976c97d9bbaa45059f164573b82fbaae41baa19f54603b495977d504df5f |
| 7 / 0.25 | 6134bcc5d592c4d86de9f997ce6777830ab30178d9cfad43896091aa44c7ed98 | 18bd2dade905555d19b7ed195b4bb053d3733871321409c560294a5d24d22fe3 | 93244126fb86abdcd3bab5e858cf89f67db49c071d61645724331ba9699b955d | 1bebdef04c6e12d8727f1ca322fc0fbc4780ddd3ffc23eec5e0cb369f3035c54 | 676ef00fb4e1b226494fd83dcfd1929ee2a9eb6d0bfc52eec93a940e30c53196 |
| 7 / 0.35 | 7ad82716bd6b4eec8dde260ef2e03dfbe9fe03f9f3c58867ab739fdb0ffa0507 | 6210bd4aa3fe074218cd36fec71a94fd2930bc7be1e9c0f86ea5e37c0934cc5e | 00b78901dc9b16dbc1f3eb007a45d34c2071e6643b03513e256f98223c36bf7e | 813494283eb518b588a2c23a6e7c32f91f10bbfcd06e1fbff755e5fc986fc63b | f522fcd4b1a3cd165e25e24dcb52684e2644444664cb5f88fad9a31744a9f32f |

### Baseline parity

The baseline candidate is (5, 0.25), candidate ID
37769b33cc663e4baf5488001252a996b9cb2ec67d0182400f12cb928015709c.
Before challenger replay, the runner:

1. validates the frozen V1.7 source and evaluation bundles;
2. validates the resolved SR/input hashes and provenance;
3. replays the V1.7 control using the approved V1.7 implementation identity;
4. compares the control replay with the persisted V1.7 evaluation;
5. replays the baseline with the current V1.8 implementation identity;
6. compares baseline semantics and aggregate micro/macro metrics exactly.

For each asset, exact equality covers source ID, resolved SR/input hashes,
candidate metrics, model bars, reference ATR, initial/final state, lifecycle
snapshots, trace snapshots, zone observations, and events. The baseline
effective hashes are the frozen V1.7 hashes shown above.

Only identities intentionally derived from the new study context may differ:
the V1.8 study/candidate/evaluation IDs and replay/trace IDs bound to the
current implementation identity. No semantic replay content or frozen input
identity is allowed to differ. Challenger hashes and IDs differ only because
the two approved geometry fields differ.

## Blast Radius Considered

Codebase graph search and call tracing covered the reused V1.7
replay_asset/evaluation flow, ResolvedSRConfig.create, cohort aggregation,
artifact validation, and the new geometry package entry points. The dependency
direction is additive:

geometry study -> V1.7 cohort replay/metrics -> approved SR replay/lifecycle

The new runner loads the published frozen source directly and contains no
Binance/provider import or network path. It does not call source preparation,
does not consume a sealed/holdout window, and does not alter the V1.7 source or
evaluation bundles. No shared existing symbol was changed, so the additive
research-only surface has no identified high/critical production blast radius.

Protected areas confirmed unchanged:

- configs/sr.yaml
- configs/sr_inputs.yaml
- V1.7 tracked source/evaluation code
- SR domain, detection, association, lifecycle, replay, serialization,
  observation, and evaluation contracts
- Binance adapters/provider code
- browser viewer/runtime code
- holdout preparation or scoring paths

Pre-existing worktree artifacts and plan drafts remain untouched and were not
staged:

- .codebase-memory/artifact.json
- .codebase-memory/graph.db.zst
- the previously untracked historical plan drafts

## Validation Performed

| Check | Result |
|---|---|
| V1.8 targeted suite | 50 passed |
| Full SR suite | 472 passed |
| SR/import boundary suites | 4 passed |
| Ruff on V1.8 source/tests | passed |
| Python compilation | passed |
| Provider/network spy around run_study | passed; no provider path reached |
| Final CLI validate | passed |
| Protected-core/config/diff checks | passed |

The focused V1.8 suite was rerun after hardening and passed 50 tests, including
all 15 selection-threshold mutation cases and synthetic selection, diagnostic,
quality-boundary, guardrail-boundary, stability, tie-break, disposition, and
undefined-denominator cases.

The provider spy rejected provider-module import attempts while the full study
completed, proving the study is network-free and source-reuse-only.

## Final Evidence

The exact evaluation command was run twice before this handoff was written:

    PYTHONPATH=src .venv/bin/python -m libs.models.sr.scripts.geometry_sensitivity.cli evaluate --config configs/sr_trials/sr_v1_8_1d_geometry_sensitivity.yaml

Both runs produced the same IDs and bytes:

| Evidence field | Value |
|---|---|
| Bundle ID | b0ea33decc9c8c40dab98bdbb90635652dc199031fc50b27d3a71a6711378941 |
| Study ID | 2a324d3a203642bf9030aede611a8d874fcb051c5b394fcb4758582d6cfbc954 |
| Disposition | RETAIN_BASELINE_GEOMETRY |
| Selected challenger | none |
| Bundle path | research/tmp_sr_v1_8/evaluation/b0ea33decc9c8c40dab98bdbb90635652dc199031fc50b27d3a71a6711378941 |
| Manifest bytes | 9,130 |
| Manifest SHA-256 | 3e50b07691d32836874ab4d729fe010c6a356b0ff477846b5e29f85267ec0feb |
| study.json bytes | 2,686,420 |
| study.json SHA-256 | 09318eb5c1281556861961c9cca104194ede39814045b6c8facba6a2ef2e65aa |
| Manifest implementation commit | fa819418aa35b7f325c7a6bf2a51a387aa97f60f |
| Manifest config hash | 86137d2c5b5e12802a5731298ab548822f23c4937d635bae5f21b77a8e7c0da7 |

The two run outputs were byte-identical, including manifest and study.json
member bytes. The final CLI validator accepted the bundle and returned the
same bundle ID, study ID, and disposition.

Semantic comparison against prior V1.8 study evidence found no changes in any
candidate, evaluation, or decision payload. Only implementation_commit and the
derived study_id changed, as required by the corrected implementation identity.

### Candidate gate matrix

Values are from the persisted decision records. Fully is structural and
aggregate eligibility; quality, guardrails, stability, and all are the
corresponding decision gates. Units is comparable asset-fold count and win is
asset-fold win fraction.

| Geometry | Fully | Quality | Guardrails | Stability | All | Median asset delta | Micro delta | Positive assets | Worst asset delta | Units | Win | Neighbor support |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 3 / 0.15 | yes | no | yes | no | no | -0.276514 | -0.072658 | 1 | -0.770287 | 21 | 0.666667 | none |
| 3 / 0.25 | yes | no | yes | yes | no | -0.065351 | 0.257041 | 1 | -0.796544 | 21 | 0.619048 | be84c1f4... |
| 3 / 0.35 | yes | no | yes | no | no | 0.005483 | 0.277034 | 2 | -0.583109 | 21 | 0.619048 | none |
| 5 / 0.15 | yes | no | no | no | no | -0.101409 | -0.118862 | 1 | -0.908167 | 21 | 0.285714 | none |
| 5 / 0.25 baseline | yes | yes | yes | yes | yes | 0.000000 | 0.000000 | 0 | 0.000000 | n/a | n/a | none |
| 5 / 0.35 | yes | no | yes | yes | no | -0.152329 | -0.200022 | 0 | -0.417586 | 21 | 0.047619 | be84c1f4... |
| 7 / 0.15 | no | no | yes | no | no | 0.063199 | 0.121785 | 2 | -0.677358 | 12 | 0.500000 | none |
| 7 / 0.25 | no | no | yes | no | no | 0.000000 | 0.087710 | 1 | -0.202818 | 15 | 0.466667 | none |
| 7 / 0.35 | no | no | yes | no | no | -0.138404 | -0.178322 | 1 | -0.996748 | 16 | 0.500000 | none |

No challenger passes all gates. The only neighbor-support ID recorded is the
full candidate ID
be84c1f446bd4f948d1d991cc80f9a52451b639e4058799bdb7fc5233c7c7f7d, for the
3/0.25 and 5/0.35 decision records.

### Fold outcome matrix

Each entry is completed first-touch count / median quality in ATR units. Fold
order is 2024_q3, 2024_q4, 2025_q1, 2025_q2, 2025_q3, 2025_q4.

    3/.15  TAO[10/-.936,10/.010,8/-.457,8/-.263,8/-1.082,7/-1.371]
            BTC[8/-.541,8/-.273,9/-.095,9/-.763,10/-.560,9/-.365]
            ETH[10/-.148,10/.765,6/-.270,6/.297,6/1.344,9/.146]
            SOL[8/.370,10/-.561,9/1.865,9/1.026,10/-.134,7/1.537]
    3/.25  TAO[10/-2.053,10/.010,8/-.166,8/-.263,8/-1.082,7/-.153]
            BTC[9/-.867,8/-.273,10/-.375,9/-.763,9/-.285,8/-.675]
            ETH[10/-.148,11/1.285,8/-.025,7/.502,7/1.099,10/.831]
            SOL[8/.370,10/-.561,8/.364,9/1.026,10/.716,7/1.537]
    3/.35  TAO[9/-1.764,10/-1.161,9/-.624,8/-.263,9/-.597,6/1.249]
            BTC[10/-.892,8/-.380,10/.067,9/-.763,9/-.496,8/-.675]
            ETH[11/-.995,11/1.285,8/.812,7/.502,8/.729,10/.578]
            SOL[8/.012,9/-.417,8/.364,9/1.026,10/.716,7/.831]
    5/.15  TAO[7/-.703,8/-.046,6/.450,5/-1.405,3/.589,4/.653]
            BTC[5/-.867,7/.056,9/-.095,5/-.774,5/-.285,7/-.365]
            ETH[10/-2.125,8/1.136,5/-1.862,5/-2.330,3/2.012,5/.131]
            SOL[7/-1.862,6/-1.624,4/-.347,6/-.274,4/-2.424,5/.482]
    5/.25  TAO[7/-1.517,8/-.046,6/.811,6/-1.155,3/.479,4/.927]
            BTC[6/-.990,7/-.157,9/-.417,7/-.774,4/-.186,6/1.153]
            ETH[10/-2.125,9/1.285,6/-1.227,6/-.914,3/2.012,6/.960]
            SOL[8/-.802,6/-1.624,3/-.425,6/-.649,4/-2.482,5/.482]
    5/.35  TAO[6/-1.735,8/-1.217,6/.432,6/-1.155,3/.479,4/.927]
            BTC[7/-1.205,7/-.157,9/-.417,7/-.774,4/-.186,6/1.153]
            ETH[10/-1.521,9/1.285,7/-1.862,6/-.914,5/1.933,6/.960]
            SOL[8/-.802,6/-1.624,3/-1.507,6/-.649,4/-2.482,5/.482]
    7/.15  TAO[4/.870,6/.010,5/.159,5/-2.176,2/-.489,4/.432]
            BTC[2/1.067,3/-.901,4/.005,1/1.324,3/-.285,5/-.365]
            ETH[6/-.209,5/.574,3/-.592,1/.502,3/1.933,4/.570]
            SOL[3/-1.862,2/-2.712,5/-.268,5/-.007,4/-2.424,3/.482]
    7/.25  TAO[4/.870,6/.010,5/.159,5/-2.176,2/.273,5/1.460]
            BTC[2/1.067,4/-.496,4/-.577,2/1.893,2/.002,4/.127]
            ETH[6/-.209,7/1.285,4/-.919,2/1.521,3/1.933,4/.831]
            SOL[4/-1.990,2/-2.712,5/-.268,5/-.541,4/-2.424,3/.482]
    7/.35  TAO[4/.463,6/-1.217,5/.159,5/-2.176,2/.273,5/1.460]
            BTC[4/-.892,4/-.725,4/-.798,2/1.893,2/.002,4/.127]
            ETH[6/-.209,7/1.285,4/-.919,3/.502,5/.359,5/1.010]
            SOL[4/-1.990,2/-2.712,4/-.894,5/-.541,4/-2.424,3/.482]

### Pooled asset matrix

Notation is completed / right-censored / median quality / invalidation rate /
event density per 100 eligible bars / churn.

| Geometry | TAOUSDT | BTCUSDT | ETHUSDT | SOLUSDT |
|---|---|---|---|---|
| 3 / 0.15 | 56/1/-.784/.464/11.840/.969 | 56/1/-.467/.446/12.933/.915 | 54/1/.111/.426/12.933/.915 | 56/2/.762/.321/12.750/.929 |
| 3 / 0.25 | 56/1/-.811/.411/11.840/.969 | 56/1/-.436/.393/12.933/.915 | 59/1/.502/.373/12.933/.901 | 56/2/.709/.304/12.750/.929 |
| 3 / 0.35 | 55/1/-.597/.309/11.475/.968 | 57/1/-.295/.368/12.933/.915 | 59/1/.502/.339/12.933/.901 | 55/2/.698/.255/12.568/.913 |
| 5 / 0.15 | 35/0/-.217/.400/8.197/.956 | 41/1/-.417/.488/10.383/.912 | 39/1/-.294/.462/10.383/.912 | 33/1/-.306/.455/8.925/.918 |
| 5 / 0.25 | 36/0/-.014/.361/8.197/.956 | 41/1/-.417/.439/10.383/.912 | 42/1/.614/.381/10.383/.912 | 34/1/-.483/.412/8.925/.918 |
| 5 / 0.35 | 35/0/-.153/.257/8.015/.955 | 42/1/-.424/.357/10.383/.912 | 44/1/.196/.386/10.383/.912 | 34/1/-.649/.412/8.925/.918 |
| 7 / 0.15 | 28/0/-.103/.357/6.922/.974 | 21/0/.104/.381/7.104/.872 | 25/0/-.064/.400/7.650/.929 | 23/1/-.268/.435/7.468/.902 |
| 7 / 0.25 | 29/0/-.217/.345/6.922/.974 | 21/1/.104/.286/7.104/.872 | 28/0/.614/.357/7.650/.929 | 24/1/-.483/.417/7.468/.902 |
| 7 / 0.35 | 29/0/-1.011/.310/6.922/.974 | 22/1/-.090/.273/7.104/.872 | 31/0/.502/.323/7.650/.929 | 24/1/-.649/.417/7.468/.902 |

### Micro and macro cohort matrix

Notation is completed / right-censored / median quality / invalidation rate /
event density / churn.

| Geometry | Micro | Macro median quality / invalidation / density / churn |
|---|---|---|
| 3 / 0.15 | 222/5/-.290/.414/12.614/.931 | -.178/.436/12.842/.922 |
| 3 / 0.25 | 227/5/.040/.370/12.614/.928 | .033/.383/12.842/.922 |
| 3 / 0.35 | 226/5/.060/.319/12.477/.923 | .104/.324/12.750/.914 |
| 5 / 0.15 | 148/3/-.336/.453/9.472/.923 | -.300/.458/9.654/.915 |
| 5 / 0.25 | 153/3/-.217/.399/9.472/.923 | -.215/.396/9.654/.915 |
| 5 / 0.35 | 155/3/-.417/.355/9.426/.923 | -.288/.372/9.654/.915 |
| 7 / 0.15 | 97/1/-.095/.392/7.286/.919 | -.083/.390/7.286/.916 |
| 7 / 0.25 | 102/2/-.129/.353/7.286/.919 | -.056/.351/7.286/.916 |
| 7 / 0.35 | 106/2/-.395/.330/7.286/.919 | -.369/.316/7.286/.916 |

### Event accounting

The persisted event accounting is created / touched / breach_started /
false_breakout / break_confirmed / expired / observed_event_count.

| Geometry | Event accounting |
|---|---|
| 3 / 0.15 | 308 / 1372 / 228 / 62 / 163 / 126 / 2259 |
| 3 / 0.25 | 308 / 1707 / 215 / 53 / 159 / 129 / 2571 |
| 3 / 0.35 | 305 / 2009 / 207 / 50 / 154 / 130 / 2855 |
| 5 / 0.15 | 228 / 771 / 157 / 47 / 109 / 103 / 1415 |
| 5 / 0.25 | 228 / 971 / 151 / 42 / 109 / 103 / 1604 |
| 5 / 0.35 | 227 / 1181 / 139 / 33 / 105 / 106 / 1791 |
| 7 / 0.15 | 169 / 545 / 107 / 39 / 65 / 91 / 1016 |
| 7 / 0.25 | 169 / 678 / 98 / 30 / 65 / 91 / 1131 |
| 7 / 0.35 | 169 / 807 / 83 / 20 / 63 / 93 / 1235 |

### Per-asset guardrails

Each tuple is invalidation-rate delta / zone-density ratio / churn-rate delta /
right-censoring-rate delta against the (5, 0.25) baseline. Full precision is
retained in study.json.

| Geometry | TAOUSDT | BTCUSDT | ETHUSDT | SOLUSDT |
|---|---|---|---|---|
| 3 / 0.15 | +0.103174 / 1.444444 / +0.013675 / +0.017544 | +0.007404 / 1.245614 / +0.003212 / -0.006266 | +0.044974 / 1.245614 / +0.003212 / -0.005074 | -0.090336 / 1.428571 / +0.010204 / +0.005911 |
| 3 / 0.25 | +0.049603 / 1.444444 / +0.013675 / +0.017544 | -0.046167 / 1.245614 / +0.003212 / -0.006266 | -0.008071 / 1.245614 / -0.010872 / -0.006589 | -0.108193 / 1.428571 / +0.010204 / +0.005911 |
| 3 / 0.35 | -0.052020 / 1.400000 / +0.012698 / +0.017857 | -0.070603 / 1.245614 / +0.003212 / -0.006568 | -0.041969 / 1.245614 / -0.010872 / -0.006589 | -0.157219 / 1.408163 / -0.005324 / +0.006516 |
| 5 / 0.15 | +0.038889 / 1.000000 / +0.000000 / +0.000000 | +0.048780 / 1.000000 / +0.000000 / +0.000000 | +0.080586 / 1.000000 / +0.000000 / +0.001744 | +0.042781 / 1.000000 / +0.000000 / +0.000840 |
| 5 / 0.35 | -0.103968 / 0.977778 / -0.001010 / +0.000000 | -0.081882 / 1.000000 / +0.000000 / -0.000554 | +0.005411 / 1.000000 / +0.000000 / -0.001034 | +0.000000 / 1.000000 / +0.000000 / +0.000000 |
| 7 / 0.15 | -0.003968 / 0.844444 / +0.018129 / +0.000000 | -0.058072 / 0.684211 / -0.040486 / -0.023810 | +0.019048 / 0.736842 / +0.016291 / -0.023256 | +0.023018 / 0.836735 / -0.015928 / +0.013095 |
| 7 / 0.25 | -0.016284 / 0.844444 / +0.018129 / +0.000000 | -0.153310 / 0.684211 / -0.040486 / +0.021645 | -0.023810 / 0.736842 / +0.016291 / -0.023256 | +0.004902 / 0.836735 / -0.015928 / +0.011429 |
| 7 / 0.35 | -0.050766 / 0.844444 / +0.018129 / +0.000000 | -0.166297 / 0.684211 / -0.040486 / +0.019669 | -0.058372 / 0.736842 / +0.016291 / -0.023256 | +0.004902 / 0.836735 / -0.015928 / +0.011429 |

## Not Changed

The following are explicitly outside this implementation:

- SR production parameters and configs;
- ATR period or ATR method;
- feature engineering, detection semantics outside the two geometry fields,
  lifecycle semantics, association semantics, replay contracts, or viewer code;
- Binance/provider calls or source preparation;
- holdout creation, holdout scoring, or any promotion decision;
- V1.7 source/evaluation artifacts;
- merge to master or any other branch.

The result is a development sensitivity study only. It is not profitability
evidence, trading-readiness evidence, or authorization for a future holdout.

## Risks or Follow-up Items

The deterministic disposition is RETAIN_BASELINE_GEOMETRY. No challenger met
the complete quality/stability protocol, so the frozen baseline geometry
(pivot span 5, width 0.25 ATR) remains in force. No geometry override is
recommended.

The dense event matrix is retained as evidence; it does not change the
approved selection decision. Any future sensitivity or holdout work requires a
new approved handoff and must preserve the frozen source and no-reuse
boundaries.

There are no blocking implementation findings known to the coder package.
This handoff is complete enough for review without additional assumptions.
