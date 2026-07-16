---
goal: Deliver the SR-V1.10 TAOUSDT context-semantics audit and visual casebook
stage: coder-to-review
date_created: 2026-07-16
last_updated: 2026-07-16
owner: Codex
status: Needs Review
tags: [handoff, quant, sr, v1.10, context-audit, lifecycle, casebook, taousdt]
source_agent: Codex quant-coder
target_agent: Quant Review / Orchestrator
---

# SR-V1.10 Context Semantics Audit

## Scope executed

Implemented the approved development-only TAOUSDT/1d context-semantics audit on
branch `feature/sr-v1.10-context-semantics-audit`.

- exact V1.9 documentation base: `676feeaac0993020355e6da155771e65642eec51`;
- authorization commit: `f7779d3a562bb53ce3d3c760d44b361b27775539`;
- implementation/remediation commit: `e52e96eb779ccc9ada0b4bef6b1082177091ebc8`;
- implementation commit remains unmerged.

The package validates the approved V1.9 study, replays the frozen causal trace,
maps the exact 36 approved pooled cases to fold-local records, and publishes a
deterministic audit ledger plus additive casebook chart payload. It does not
contact Binance, construct a provider/source capsule, access or score a
holdout, change SR model behavior/configuration, or make a promotion decision.

## Changed-file inventory

Added:

- `configs/sr_trials/sr_v1_10_taousdt_1d_context_audit.yaml`;
- `src/libs/models/sr/scripts/context_audit/__init__.py`;
- `src/libs/models/sr/scripts/context_audit/artifacts.py`;
- `src/libs/models/sr/scripts/context_audit/audit.py`;
- `src/libs/models/sr/scripts/context_audit/cli.py`;
- `src/libs/models/sr/scripts/context_audit/config.py`;
- `src/libs/models/sr/scripts/context_audit/contracts.py`;
- `src/libs/models/sr/scripts/context_audit/runner.py`;
- `tests/models/sr/scripts/context_audit/__init__.py`;
- `tests/models/sr/scripts/context_audit/conftest.py`;
- `tests/models/sr/scripts/context_audit/test_artifacts.py`;
- `tests/models/sr/scripts/context_audit/test_audit.py`;
- `tests/models/sr/scripts/context_audit/test_config.py`;
- `tests/models/sr/scripts/context_audit/test_import_boundaries.py`;
- `tests/models/sr/tools/zone_viewer/test_context_audit.py`.
- `src/libs/models/sr/tools/zone_viewer/src/casebook.js`;
- `src/libs/models/sr/tools/zone_viewer/tests/casebook.test.js`.

Modified additively:

- `src/libs/models/sr/tools/zone_viewer/index.html`;
- `src/libs/models/sr/tools/zone_viewer/payload.py`;
- `src/libs/models/sr/tools/zone_viewer/server.py`;
- `src/libs/models/sr/tools/zone_viewer/src/main.js`;
- `src/libs/models/sr/tools/zone_viewer/src/styles.css`.
- `src/libs/models/sr/tools/zone_viewer/package.json`;
- `tests/models/sr/scripts/context_audit/test_artifacts.py`;
- `tests/models/sr/scripts/context_audit/test_audit.py`.

The legacy viewer payload/server contract remains unchanged when the optional
casebook block is absent. The casebook mode contains all 36 cases, filters the
visible selection without mutating payload data, renders the selected zone and
events, exposes pooled/fold-local metrics, and retains the existing toggles,
hover details, attribution, and pinned Lightweight Charts 5.2.0 boundary.

The remediation commit adds deterministic chronological marker ordering with
stable same-bar ordering, clears all casebook state when filters produce no
cases, and permanently renders the exact V1.9 disposition in the viewer
notice. It also adds focused viewer, causal, identity, and rehashed tamper
regressions and fixes the previously unused Ruff import.

## Frozen input identities

| Input | Identity |
|---|---|
| V1.9 config | `configs/sr_trials/sr_v1_9_taousdt_1d_baseline_adequacy.yaml` |
| V1.9 config hash | `ae8b290674f8c9feb3ce630910753f44dcff87a64795428f614735b0cc2dc9a9` |
| V1.9 bundle | `12af91cecc3582606da7c41c0c1beaf0320aa17eef8c52edf615214cf0a34df6` |
| V1.9 study | `ed19698fec505e2e8cf1057c41336da7c0720bcf412530244139e5c523f12c9f` |
| V1.9 implementation | `542faeb0991617ec38a3f7cc13551a26c0f567f0` |
| V1.9 disposition | `BASELINE_NOT_BETTER_THAN_NAIVE_NULL` |
| V1.7 source bundle | `6b5a0a81117ba299516fb67ca2da81b3cb6e6f35ed6a85986a27689205a565d9` |
| TAOUSDT source member | `fc1ba274454f277a40f005f542fdfd4e6e752e5afa2e1050f3582b21fd8b1120` |
| V1.7 evaluation bundle | `824e9265a63073ba792762a891adf52deec9677d791c40641dc0107c1f2b840d` |
| V1.7 evaluation ID | `49a895360774ec0c46349eae2d1ec6f56e7262e5f1411ab992f9886d9040fa8d` |
| V1.8 study bundle | `b0ea33decc9c8c40dab98bdbb90635652dc199031fc50b27d3a71a6711378941` |
| V1.8 study ID | `2a324d3a203642bf9030aede611a8d874fcb051c5b394fcb4758582d6cfbc954` |
| V1.8 baseline candidate | `37769b33cc663e4baf5488001252a996b9cb2ec67d0182400f12cb928015709c` |
| Production SR config hash | `cb9b4143921de95c5423899a5655fef0b186cf1f8e9a84c69427bf64df030299` |
| Frozen input config hash | `5ece92803341696df06efa0dba5d7a44ee0f5451aa3ce6555d3a4ef6c59fab6d` |
| TAOUSDT original source bundle | `d210494937ebcd4347e026b8ac02bff3105065e5455752b8690d449def357925` |
| TAOUSDT frozen bars SHA-256 | `703367048f4ed7dc432ca9dfe0ad4afdc5a56eb2a508597ef00bdc3de8b81163` |

The audit uses 629 frozen daily bars from `2024-04-11T00:00:00Z` through
`2025-12-31T00:00:00Z`, Wilder RMA ATR(14) with SMA seed, the unchanged eight SR
parameters, next-bar outcome start, ten-bar horizon, and the six approved
half-open folds. State continues across fold boundaries.

## Final evidence

The evaluate command was run twice at implementation/remediation commit
`e52e96eb779ccc9ada0b4bef6b1082177091ebc8`:

```text
PYTHONPATH=src .venv/bin/python -m libs.models.sr.scripts.context_audit.cli evaluate configs/sr_trials/sr_v1_10_taousdt_1d_context_audit.yaml --repo-root .
```

Both runs produced the same IDs, audit bytes, chart bytes, metrics, mappings,
and disposition:

| Evidence field | Value |
|---|---|
| Bundle ID | `a592276b9fed7c24949ad33b503a7b65474e10f4e3088fe734282401ac058a56` |
| Audit ID | `147df6b76fea1a2d8cf5f77840f4e82af6e7d7e8207410e2c43249442ea81c07` |
| Trace ID | `5e58eeb1e3aef84a096d348779d92d76268da619ad4445dee397d56fe688047f` |
| Config hash | `1ae6cdf31951e20540a9625a85e593e9bfbb9520364b68d6e783f05ab477207f` |
| Audit status | `COMPLETE` |
| V1.9 disposition | `BASELINE_NOT_BETTER_THAN_NAIVE_NULL` |
| Evidence path | `research/tmp_sr_v1_10/audit/a592276b9fed7c24949ad33b503a7b65474e10f4e3088fe734282401ac058a56` |
| Chart identity hash | `e3ddf8d2e4b4dca4ee29de32afe4cfa10f87015c9a98302498b2edf3893a5344` |

Final published member bytes:

| Member | Bytes | SHA-256 |
|---|---:|---|
| `manifest.json` | 9854 | `482dc10c3a5eaa1142b1b8b7967eea39464f9975ceef14b3aaddb04c66588baf` |
| `audit.json` | 266791 | `27afe6242cc68e0222c7f93ef212b9ad87faaaf53c1b21e6edcbc5a8e2eaceb1` |
| `chart_payload.json` | 605404 | `621df3d8cbd6191567c00b31bed54848acf4a91d0f1f920d7fc1ea2f70cf0714` |

The bundle identity basis correctly uses the unbound chart payload member:
`chart_payload.json`, 605342 bytes, SHA-256
`ba2bfdb03d306db01adfdcd36285f0890f737bb73eb7d73e505a7a54a7adc30a`.
The final chart member then binds the bundle ID and has the published hash above.

## Exact audit accounting

The ledger contains 36 unique cases, 36 unique fold-local records, 31 persisted
comparisons, 36 zones, 629 source candles, and 242 lifecycle events. All cases
enter and exit the touch bar with `ACTIVE` status.

### Outcome populations

| Population | Total | Completed | Right-censored | Folds | Median quality |
|---|---:|---:|---:|---:|---:|
| Approved pooled | 36 | 36 | 0 | 6 | `-0.014070405071082426` |
| Fold-local | 36 | 34 | 2 | 6 | `0.1807362526958346` |
| Comparable mapped | 31 | 31 | 0 | 5 | `0.12499422337239618` |

Fold accounting is:

| Fold | Cases | Fold-local completed | Fold-local censored | Comparisons |
|---|---:|---:|---:|---:|
| `2024_q3` | 7 | 7 | 0 | 7 |
| `2024_q4` | 8 | 8 | 0 | 8 |
| `2025_q1` | 7 | 6 | 1 | 6 |
| `2025_q2` | 6 | 6 | 0 | 6 |
| `2025_q3` | 4 | 3 | 1 | 0 |
| `2025_q4` | 4 | 4 | 0 | 4 |

`2025_q3` is non-comparable; no comparison is imputed.

### Side and lifecycle accounting

| Side | Cases |
|---|---:|
| SUPPORT | 19 |
| RESISTANCE | 17 |

| Horizon lifecycle class | SUPPORT | RESISTANCE | Total |
|---|---:|---:|---:|
| `BREAK_CONFIRMED` | 6 | 7 | 13 |
| `FALSE_BREAKOUT_NO_CONFIRMED_BREAK` | 3 | 2 | 5 |
| `EXPIRED_NO_BREAK_OR_FALSE_BREAKOUT` | 1 | 1 | 2 |
| `NO_TERMINAL_OR_FAKEOUT_EVENT` | 9 | 7 | 16 |

Horizon terminal status is `ACTIVE` for 21 cases, `BROKEN` for 13, and
`EXPIRED` for 2. Event accounting is 36 `CREATED`, 164 `TOUCHED`, 20
`BREACH_STARTED`, 7 `FALSE_BREAKOUT`, 13 `BREAK_CONFIRMED`, and 2 `EXPIRED`
events, for 242 total.

### Touch-close accounting

| Touch close location | SUPPORT | RESISTANCE | Total |
|---|---:|---:|---:|
| `BELOW_BAND` | 1 | 14 | 15 |
| `INSIDE_BAND` | 6 | 2 | 8 |
| `ABOVE_BAND` | 12 | 1 | 13 |

Zone age at touch:

| Side | Count | Minimum | Median | Maximum |
|---|---:|---:|---:|---:|
| SUPPORT | 19 | 2 | 10 | 41 |
| RESISTANCE | 17 | 1 | 4 | 44 |

## V1.9 parity and research conclusion

The audit preserves the approved V1.9 result without reinterpretation:

- pooled real baseline median quality: `-0.014070405071082426`;
- pooled control resistance median: `0.20682616539078957`;
- pooled control support median: `-0.20682616539078957`;
- pooled median excess quality: `0.026200435413100243`;
- positive comparable-fold fraction: `0.4`;
- worst comparable-fold excess: `-1.1546071281136923`;
- fold-local completed counts: `7, 8, 6, 6, 3, 4`;
- no holdout was opened or scored.

V1.10 is diagnostic evidence only. It does not change the negative V1.9
disposition, establish profitability/generalization, authorize parameter or
feature work, or authorize production promotion.

## Validation performed

| Check | Result |
|---|---|
| Focused Python audit/viewer suite | 39 passed |
| Complete `tests/models/sr` suite | 532 passed in 622.11s |
| Node viewer suite (`npm test`) | 15 passed |
| Python compilation | passed |
| `git diff --check` | passed |
| `node --check src/libs/models/sr/tools/zone_viewer/src/main.js` | passed |
| Ruff | passed with `/Users/aloobhujia/.local/bin/ruff` |
| Provider/network/source-preparation spies | passed; no provider call or new capsule |
| Semantic artifact/tamper validation | passed |

The viewer regression suite covers all 36 case selections, fold/side/completion
filters, selected-case state, exact outcome-window bounds, deterministic
marker ordering, empty-filter clearing, metrics, disposition rendering, and
legacy primitive compatibility. The audit regressions cover causal event
ordering, nested identity reuse, rehashed payload tampering, and metric
reconciliation.

Focused Python command:

```text
PYTHONPATH=src .venv/bin/pytest -q tests/models/sr/scripts/context_audit tests/models/sr/tools/zone_viewer
```

Node command:

```text
(cd src/libs/models/sr/tools/zone_viewer && npm test)
```

The complete SR run was executed with:

```text
PYTHONPATH=src .venv/bin/pytest -q tests/models/sr
```

## Final CLI validation and viewer command

Final validation is required from the later documentation HEAD; the validator
defaults to the manifest implementation commit and retains explicit mismatch
rejection:

```text
PYTHONPATH=src .venv/bin/python -m libs.models.sr.scripts.context_audit.cli validate configs/sr_trials/sr_v1_10_taousdt_1d_context_audit.yaml research/tmp_sr_v1_10/audit/a592276b9fed7c24949ad33b503a7b65474e10f4e3088fe734282401ac058a56 --repo-root .
```

Executed from the documentation HEAD after the implementation commit; result:
`audit_status=COMPLETE`, `case_count=36`, bundle
`a592276b9fed7c24949ad33b503a7b65474e10f4e3088fe734282401ac058a56`, and
unchanged disposition `BASELINE_NOT_BETTER_THAN_NAIVE_NULL`.

Serve the verified casebook locally with:

```text
PYTHONPATH=src .venv/bin/python -c "from libs.models.sr.tools.zone_viewer.server import serve_bundle; serve_bundle('src/libs/models/sr/tools/zone_viewer', 'research/tmp_sr_v1_10/audit/a592276b9fed7c24949ad33b503a7b65474e10f4e3088fe734282401ac058a56')"
```

### Browser smoke status

Mac Chrome smoke pending; no Mac Chrome browser backend is available in the
coder execution environment, so no visual approval claim is made and the Chrome
version is not yet recorded. The Mac Chrome smoke must
verify no console errors, all 36 cases and filters, one-zone/selected-event
rendering, exact outcome windows, distinguishable pooled/fold-local metrics,
absence of unpersisted null/excess values, support/resistance geometry,
terminal/event toggles, hover, pan/zoom, attribution, deterministic marker
ordering, empty-filter clearing, exact permanent disposition, bundle ID, and
the unchanged V1.9 negative disposition.

## Worktree and boundaries

Generated evidence under `research/tmp_sr_v1_10` remains untracked. Pre-existing
user-owned state was preserved and excluded from both commits:

- modified `.codebase-memory/artifact.json`;
- deleted `.codebase-memory/graph.db.zst`;
- historical untracked plan drafts under `plans/`.

No merge, V1.11 work, parameter change, feature change, production change,
provider call, source refresh, holdout access, or database/persistence service
was introduced or authorized.

## Follow-up

Complete the Mac browser smoke and route the resulting diagnostic evidence to
architecture/research review. Any next hypothesis, foundation correction, or
decision to stop the detector family requires a separately approved plan.
