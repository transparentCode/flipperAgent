# Mature Trendlines L1-B2
## Ordered, Revision-Aware Point-in-Time Snapshot History

### 1. Disposition

Implemented L1-B2 as uncommitted workspace changes. Boundary history is now ordered by market event time, retains content revisions by knowledge time, rejects identity conflicts, and resolves retention/context policy from typed canonical YAML configuration.

No commit, merge, rebase, cherry-pick, provider call, or dependency installation was performed.

### 2. Starting branch and commit

    branch: research/legacy-trendlines-quality-stability-v1
    starting HEAD: 2fbeabb96099a62a145fc8905b800d3509dece8c
    starting subject: feat: add causal trendline snapshot identities

### 3. Worktree/environment proof

Pre-change worktree was clean. Validation used the repository venv Python, local Ruff, and PYTHONPATH=src:$PWD. The codebase-memory indexer crashed while indexing this checkout and the project was not available in the graph; live source inspection was used as the permitted fallback. No dependencies were installed.

### 4. Baseline ordering defect

Starting deque history reproduced:

    inserted: 02:00, 01:00, 01:00
    order: 02:00, 01:00, 01:00
    latest: 01:00
    duplicates: accepted, count=3
    knowledge_time: absent

Starting canonical baseline: 322 passed. RegimeV2 adapter baseline: 6 passed.

### 5. YAML history configuration

Added typed SnapshotHistoryPolicy, SnapshotHistoryOverride, and immutable SnapshotHistoryPolicies. Canonical YAML now declares:

    history:
      max_logical_snapshots_per_key: 256
      max_revisions_per_snapshot: 8
      context_limit: 5

Unknown history fields and capacities below one fail closed.

### 6. Global/asset/timeframe resolution

resolve_snapshot_history_policy(config, asset, timeframe) applies global policy, then optional assets.{asset}.timeframes.{timeframe}.history override. Tested override:

    global: BTCUSDT/1h -> 512 logical, 12 revisions, context 8
    fallback: ETHUSDT/1h -> 256 logical, 8 revisions, context 5

Policy lookup is O(1) per key. Missing global policy makes TrendlineSnapshotHistory.from_config() fail closed.

### 7. Knowledge-time contract

TrendlineSnapshot.known_at is timezone-aware UTC and must be at or after event timestamp/as_of. Omitted first-revision knowledge time defaults deterministically to event time. New revisions require explicit known_at; naive and earlier values are rejected. No model calls current time.

### 8. Identity validation

Strict add() requires boundary-stage BoundaryResult.snapshot_identity, matching asset/timeframe, and matching source as_of. Identity-less manual boundaries are rejected by strict history insertion. Standalone TrendlineSnapshot.from_boundary() remains compatible.

### 9. Duplicate semantics

Exact (snapshot_id, revision_id, known_at) duplicates are idempotent and return stored snapshot. Reusing a revision with another knowledge time raises SnapshotIdentityConflictError. Different revisions cannot share one knowledge time.

### 10. Revision insertion semantics

New revisions share logical snapshot_id and use distinct revision_id values. Revisions remain queryable through revision_history() and are ordered by known_at. Late corrections insert without replacing earlier evidence.

### 11. Ordered internal structure

Each asset/timeframe bucket contains ordered logical snapshots by as_of, ordered revisions by known_at, and O(1) logical/revision lookup maps. Chronological appends append directly; out-of-order placement uses bisect; no full sort runs after insertion.

### 12. Retention semantics

Logical capacity prunes oldest complete logical groups. Events older than retained floor raise SnapshotRetentionError. Revision capacity raises SnapshotRevisionCapacityError and never discards earlier revisions. count() remains logical-count compatible; logical_count() and revision_count() are also exposed.

### 13. get_exact_at evidence

get_exact_at(asset, timeframe, as_of, known_at=...) selects exact event time and latest revision with known_at <= query knowledge time. Dedicated test selects base revision before correction knowledge and corrected revision after it.

### 14. get_state_at evidence

get_state_at() selects latest event at or before requested as_of, then walks backward when that event has no revision known by query known_at. Future events and future-known corrections are excluded.

### 15. Existing API compatibility

Preserved and corrected: latest, history, history_before, temporal_history, snapshots, and count. Added get_exact_at, get_state_at, revision_history, logical_count, and revision_count. temporal_history default limit comes from resolved context_limit; explicit caller limit remains query-only.

### 16. RegimeV2 integration

TrendlineFeatureConfig.history_limit defaults to None; omission uses history policy context limit and explicit values affect query context only. Adapter passes explicit UTC known_at to history_before() and add().

Shadow collector constructs TrendlineSnapshotHistory.from_config(load_trendlines_config()). Its CLI option defaults to None; storage capacity no longer derives from query limit.

### 17. Dedicated tests

Added exactly 22 non-parametrised tests in test_revision_history.py, covering policy loading, strict identity, knowledge time, duplicate/correction semantics, causal queries, ordering, retention, revision capacity, and key isolation.

### 18. Point-in-time causality evidence

    event snapshots: ordered by as_of
    revisions: ordered by known_at
    future event: excluded
    future-known correction: excluded
    late event not yet known: prior known event returned

No revision becomes visible before declared knowledge time.

### 19. Performance baseline

Deterministic identity-bearing fixture:

    100,000 hourly event boundaries
    capacity: 256 logical snapshots, 8 revisions, context 5
    fixture hash: b721335f3ceb6d6b19b08b98ca844d76f832bd18bc2567c520827db109200cc3
    repetitions: 5

Old deque implementation was reconstructed from starting commit 2fbeabb for equivalent comparison. Median batch timings:

    operation             old deque       L1-B2 store
    100k chronological add 90.218 ms       415.155 ms
    100k latest queries    14.782 ms        26.022 ms
    100k history_before   732.309 ms      3352.787 ms

### 20. Performance post-change

    100k get_state_at queries:  76.270 ms = 0.763 us/query
    2048 out-of-order adds:      9.629 ms
    append delta:               +3.25 us/add versus old deque

Append relative overhead exceeds 25%, but absolute added cost is below required 5 us/add; acceptance requires both conditions. get_state_at is below 50 us/query. No full sort, frame work, ATR work, or model work occurs in history operations.

### 21. Canonical regression

    344 collected
    344 passed

Required focused history/config group: 62 passed.

### 22. Consumer regression

    tests/test_regime_v2_trendline_feature_producer.py: 6 passed
    tests/test_regime_v2_shadow_binance_collector.py: 7 passed

Shadow collector --help succeeds and exposes --trendline-history-limit with YAML-backed storage semantics. Offline workflow group: 20 passed.

### 23. Static validation

    targeted Ruff: All checks passed
    compileall: passed
    git diff --check: passed

Repository-local __pycache__ directories were removed after validation.

### 24. Files changed

    M  src/libs/models/regime_v2/adapters/trendline_feature_producer.py
    M  src/libs/models/regime_v2/scripts/collect_shadow_binance.py
    M  src/libs/models/trendlines/boundary/__init__.py
    M  src/libs/models/trendlines/boundary/history.py
    A  src/libs/models/trendlines/config/history_config.py
    M  src/libs/models/trendlines/config/__init__.py
    M  src/libs/models/trendlines/config/base_config.py
    M  src/libs/models/trendlines/config/loader.py
    M  src/libs/models/trendlines/config/trendlines.yaml
    M  src/libs/models/trendlines/docs/architecture.md
    M  src/libs/models/trendlines/docs/boundary.md
    M  src/libs/models/trendlines/docs/config.md
    M  src/libs/models/trendlines/tests/test_boundary_history.py
    A  src/libs/models/trendlines/tests/test_revision_history.py
    M  tests/test_regime_v2_trendline_feature_producer.py

### 25. Git status

Expected after handoff creation: only authorized paths above plus this new handoff are dirty/untracked. No unrelated path is in scope. No commit was made.

### 26. Commands executed

    git branch --show-current
    git rev-parse HEAD
    git log -5 --oneline
    git status --short --untracked-files=all
    pytest canonical collect/run
    pytest RegimeV2 adapter
    pytest revision/config/history focused groups
    pytest shadow collector tests
    python -m libs.models.regime_v2.scripts.collect_shadow_binance --help
    compileall canonical package and changed consumers
    targeted Ruff over changed/new Python files
    git diff --check
    ephemeral five-repetition history benchmarks

### 27. Residual risks

History remains process-local and non-persistent. Revision replacement across process restarts, database durability, future-history rejection in signal contexts, and signal OHLCV timestamp alignment remain outside L1-B2. Direct TrendlinesConfig() construction has no hidden history policy; production history construction fails until config supplies the YAML history block.

### 28. Recommended next phase

    L1-B3 — Signal history and OHLCV-context timestamp alignment

### Required conclusion

Trendline boundary history is ordered by event time. Multiple content revisions are retained by logical snapshot. Historical queries cannot observe revisions not yet known at requested knowledge time. Retention and context limits resolve from YAML with global and asset/timeframe precedence. No model algorithm or numerical trendline hyperparameter changed.

Final disposition:

    READY_FOR_L1B3_SIGNAL_CONTEXT_ALIGNMENT
