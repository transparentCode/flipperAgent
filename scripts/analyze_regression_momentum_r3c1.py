"""Deterministic R3C1 descriptive adequacy study for the approved R3B graph.

This module is intentionally research-only.  It validates one frozen local
CSV, compiles the existing R3B Decision graph once, replays closed bars through
the bounded public Decision seams, and writes descriptive artifacts.  It does
not contain a second Momentum or regression implementation and has no network
or provider fallback.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import math
import statistics
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml

from apps.decision_app.composition import build_production_composition
from apps.decision_app.data.resolver import compile_data_plan
from apps.decision_app.domain.market_state import (
    BarStore,
    MarketSeriesKey,
    compile_bar_store_capacities,
)
from apps.decision_app.domain.view import DecisionViewBuilder
from apps.decision_app.features.engine import FeatureEngine
from apps.decision_app.features.planning import (
    compile_feature_bar_store_capacities,
    compile_feature_plan,
    merge_bar_store_capacities,
)
from apps.decision_app.observers.momentum_regression import (
    MOMENTUM_REGRESSION_OBSERVATION_ARTIFACT_TYPE,
)
from apps.decision_app.planning.planner import compile_decision_plan
from apps.decision_app.planning.readiness import compile_lane_market_requirements
from apps.decision_app.runtime.models import ModelRuntime
from apps.decision_app.settings import load_decision_config
from libs.common.config import ConfigManager
from libs.contracts.decision import CausalBarView
from libs.models.momentum.adapters.decision_plugin import (
    MOMENTUM_MODEL_SPEC,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = (
    ROOT / "research" / "regression_r3c" / "btcusdt_1h_momentum_context_utility_v1.yaml"
)
EXPECTED_BASE_SHA = "4647a04dc53a7ffd3de85a2f84b10bae4be9cefa"
EXPECTED_CUMULATIVE_MANIFEST = (
    "2085c0f9cf290e763c97b016bb2ea38a2cc22559500d357cf475c2d085b017e0"
)
EXPECTED_R3P_MANIFEST = (
    "93f8c140560e5a5f6237fe4805e309ab07f3fdbcbd77b9bbd33f127d26dce8cc"
)
EXPECTED_SOURCE_SHA = "3061187fd7092131e7df221fb1c23ea4427ba9754284910d79d47872858c0f66"
EXPECTED_GLOBAL_SHA = "542e778511049970241bf10ad33a5517c60eca13ef9457971864d565eebb2ae9"
EXPECTED_BTC_SHA = "cf9f2a5cec2380ecc81c4548cebd52e8a2343f69ff3a59c5485013a6c8135edc"
EXPECTED_M3_SHA = "6fcd3d736524b513a63f244a3268478a658924cd571a62a72ec33958ad67972c"
EXPECTED_M4_SHA = "3d1339be919e8d176dcd1053cb1c42f46bf6a2dc5f62647114b805faea1e4792"
EXPECTED_SOURCE_CONFIG_HASH = "30d530f70382"
EXPECTED_CHANNEL_CONFIG_HASH = (
    "550f7e645487cb2f04fb5994919452101113d6bdb3aef34fc58b2deb792d1fc2"
)
EXPECTED_CONTEXT_ID = "structural_channel_location_one_step_v1"
EXPECTED_HORIZONS = (1, 2, 4, 8, 16)
EXPECTED_SOURCE_HEADER = (
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_volume",
    "trades",
    "taker_buy_base",
    "taker_buy_quote",
    "ignore",
)
EXPECTED_FOLDS = ("development", "validation", "holdout")
EXPECTED_ARTIFACT_NAMES = (
    "checksums.json",
    "conditional_metrics.json",
    "coverage_summary.json",
    "observation_ledger.jsonl",
    "source_identity.json",
    "study_manifest.json",
    "study_summary.md",
)
CATEGORICAL_FIELDS = (
    "region",
    "previous_region",
    "upper_outer_breach",
    "lower_outer_breach",
    "reentered_from_upper_outer",
    "reentered_from_lower_outer",
)
CONTINUOUS_FIELDS = (
    "slope_log_per_hour",
    "fit_quality",
    "outer_channel_position",
    "outer_width_fraction",
)
METRIC_FIELDS = (
    "mean_aligned_log_return",
    "median_aligned_log_return",
    "continuation_rate",
    "mean_favorable_excursion_log",
    "median_favorable_excursion_log",
    "mean_adverse_excursion_log",
    "median_adverse_excursion_log",
    "mean_momentum_conviction",
)
R3B_ONLY_PATHS = frozenset(
    {
        "src/apps/decision_app/composition.py",
        "src/apps/decision_app/observers/__init__.py",
        "src/apps/decision_app/observers/momentum_regression.py",
        "tests/decision/fixtures/regression_r3b/assets/BTC.yaml",
        "tests/decision/fixtures/regression_r3b/global.yaml",
        "tests/decision/integration/test_r3b_momentum_regression_shadow.py",
        "tests/decision/test_momentum_regression_observer.py",
    }
)
R3C1_PATH_PREFIXES = (
    "artifacts/regression_r3c/btcusdt_1h_momentum_context_utility_v1/",
    "research/regression_r3c/",
    "scripts/analyze_regression_momentum_r3c1.py",
    "tests/scripts/test_analyze_regression_momentum_r3c1.py",
)


class StudyBlocked(RuntimeError):
    """Raised when an R3C1 fail-closed condition is met."""


def _blocked(message: str) -> StudyBlocked:
    return StudyBlocked(message)


def _require_exact_keys(
    value: Mapping[str, Any], expected: set[str], field: str
) -> None:
    actual = set(value)
    if actual != expected:
        raise _blocked(
            f"{field} keys mismatch; missing={sorted(expected - actual)}, "
            f"unexpected={sorted(actual - expected)}"
        )


def _require_mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _blocked(f"{field} must be a mapping")
    return value


def _require_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _blocked(f"{field} must be non-empty text")
    return value.strip()


def _parse_utc(value: object, field: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        text = value.strip()
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise _blocked(f"{field} has an invalid UTC datetime") from exc
    else:
        raise _blocked(f"{field} must be an explicit UTC datetime")
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise _blocked(f"{field} must be timezone-aware UTC")
    return parsed.astimezone(UTC)


def _iso(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise _blocked("semantic datetime is not UTC")
    rendered = value.astimezone(UTC).isoformat()
    return rendered.replace("+00:00", "Z")


def _canonical_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    if isinstance(value, datetime):
        return _iso(value)
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise _blocked("non-finite Decimal in semantic value")
        return str(value)
    return value


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        _canonical_value(value),
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class StudyConfig:
    raw: Mapping[str, Any]
    path: Path
    source_path: Path
    source_sha256: str
    source_row_count: int
    source_asset: str
    source_timeframe: str
    first_open_time: datetime
    last_open_time: datetime
    source_end: datetime
    folds: Mapping[str, tuple[datetime, datetime]]
    horizons: tuple[int, ...]
    output_root: Path
    semantic_digest: str


def load_study_config(path: Path = CONFIG_PATH) -> StudyConfig:
    """Load the strict research-only R3C1 YAML contract."""

    path = Path(path).resolve()
    try:
        raw_value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise _blocked(f"cannot load study config: {exc}") from exc
    root = _require_mapping(raw_value, "study config")
    _require_exact_keys(
        root,
        {"study", "source", "r3b", "identities", "folds", "outcome_horizons", "output"},
        "study config",
    )

    study = _require_mapping(root["study"], "study")
    _require_exact_keys(study, {"id", "version"}, "study")
    if _require_text(study["id"], "study.id") != (
        "regression_r3c1_btcusdt_1h_momentum_context_utility_v1"
    ):
        raise _blocked("study.id is not the approved R3C1 identity")
    if _require_text(study["version"], "study.version") != "1":
        raise _blocked("study.version is not supported")

    source = _require_mapping(root["source"], "source")
    _require_exact_keys(
        source,
        {
            "path",
            "sha256",
            "row_count",
            "asset",
            "timeframe",
            "first_open_time",
            "last_open_time",
            "source_end",
        },
        "source",
    )
    source_path_text = _require_text(source["path"], "source.path")
    source_path = (ROOT / source_path_text).resolve()
    source_sha = _require_text(source["sha256"], "source.sha256")
    if source_sha != EXPECTED_SOURCE_SHA:
        raise _blocked("study config source SHA is not the frozen R3C1 SHA")
    if source["row_count"] != 36481 or isinstance(source["row_count"], bool):
        raise _blocked("study config source row_count must be 36481")
    source_asset = _require_text(source["asset"], "source.asset")
    source_timeframe = _require_text(source["timeframe"], "source.timeframe")
    if (source_asset, source_timeframe) != ("BTCUSDT", "1h"):
        raise _blocked("study source must be BTCUSDT/1h")
    first_open = _parse_utc(source["first_open_time"], "source.first_open_time")
    last_open = _parse_utc(source["last_open_time"], "source.last_open_time")
    source_end = _parse_utc(source["source_end"], "source.source_end")
    if (first_open, last_open, source_end) != (
        datetime(2022, 1, 1, tzinfo=UTC),
        datetime(2026, 3, 1, tzinfo=UTC),
        datetime(2026, 3, 1, 1, tzinfo=UTC),
    ):
        raise _blocked("study source temporal coverage is not the predeclared coverage")

    r3b = _require_mapping(root["r3b"], "r3b")
    _require_exact_keys(
        r3b,
        {
            "global_fixture",
            "global_sha256",
            "btc_fixture",
            "btc_sha256",
            "m3_artifact_sha256",
            "m4_artifact_sha256",
            "cumulative_manifest_sha256",
            "r3p_manifest_sha256",
        },
        "r3b",
    )
    for key, expected in (
        ("global_sha256", EXPECTED_GLOBAL_SHA),
        ("btc_sha256", EXPECTED_BTC_SHA),
        ("m3_artifact_sha256", EXPECTED_M3_SHA),
        ("m4_artifact_sha256", EXPECTED_M4_SHA),
        ("cumulative_manifest_sha256", EXPECTED_CUMULATIVE_MANIFEST),
        ("r3p_manifest_sha256", EXPECTED_R3P_MANIFEST),
    ):
        if _require_text(r3b[key], f"r3b.{key}") != expected:
            raise _blocked(f"r3b.{key} is not the approved identity")

    identities = _require_mapping(root["identities"], "identities")
    _require_exact_keys(
        identities,
        {"source_config_hash", "channel_config_hash", "context_id"},
        "identities",
    )
    if (
        _require_text(identities["source_config_hash"], "identities.source_config_hash")
        != EXPECTED_SOURCE_CONFIG_HASH
        or _require_text(
            identities["channel_config_hash"], "identities.channel_config_hash"
        )
        != EXPECTED_CHANNEL_CONFIG_HASH
        or _require_text(identities["context_id"], "identities.context_id")
        != EXPECTED_CONTEXT_ID
    ):
        raise _blocked("regression source/channel/context identity drifted")

    folds_value = _require_mapping(root["folds"], "folds")
    _require_exact_keys(folds_value, set(EXPECTED_FOLDS), "folds")
    folds: dict[str, tuple[datetime, datetime]] = {}
    for name in EXPECTED_FOLDS:
        item = _require_mapping(folds_value[name], f"folds.{name}")
        _require_exact_keys(item, {"start", "end"}, f"folds.{name}")
        start = _parse_utc(item["start"], f"folds.{name}.start")
        end = _parse_utc(item["end"], f"folds.{name}.end")
        if end <= start:
            raise _blocked(f"folds.{name} must be increasing")
        folds[name] = (start, end)
    expected_fold_bounds = (
        folds["development"]
        == (
            datetime(2022, 1, 1, tzinfo=UTC),
            datetime(2024, 1, 1, tzinfo=UTC),
        ),
        folds["validation"]
        == (
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2025, 1, 1, tzinfo=UTC),
        ),
        folds["holdout"][0] == datetime(2025, 1, 1, tzinfo=UTC),
        folds["holdout"][1] == source_end,
    )
    if not all(expected_fold_bounds):
        raise _blocked("chronological R3C1 folds do not match the predeclared folds")

    horizons_value = root["outcome_horizons"]
    if (
        isinstance(horizons_value, (str, bytes))
        or not isinstance(horizons_value, Sequence)
        or tuple(horizons_value) != EXPECTED_HORIZONS
    ):
        raise _blocked("outcome_horizons must be exactly [1, 2, 4, 8, 16]")

    output = _require_mapping(root["output"], "output")
    _require_exact_keys(output, {"root"}, "output")
    output_text = _require_text(output["root"], "output.root")
    if output_text != "artifacts/regression_r3c/btcusdt_1h_momentum_context_utility_v1":
        raise _blocked("output.root is not the approved R3C1 artifact root")

    return StudyConfig(
        raw=root,
        path=path,
        source_path=source_path,
        source_sha256=source_sha,
        source_row_count=int(source["row_count"]),
        source_asset=source_asset,
        source_timeframe=source_timeframe,
        first_open_time=first_open,
        last_open_time=last_open,
        source_end=source_end,
        folds=folds,
        horizons=EXPECTED_HORIZONS,
        output_root=(ROOT / output_text).resolve(),
        semantic_digest=sha256_bytes(canonical_json_bytes(root)),
    )


def _source_datetime(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise _blocked(f"{field} must use the source's UTC text form")
    try:
        parsed = datetime.strptime(f"{value}+0000", "%Y-%m-%d %H:%M:%S%z")
    except ValueError as exc:
        raise _blocked(f"{field} has an invalid source timestamp") from exc
    return parsed.replace(tzinfo=UTC)


def _source_close_datetime(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise _blocked(f"{field} must use the source's UTC text form")
    try:
        parsed = datetime.strptime(f"{value}+0000", "%Y-%m-%d %H:%M:%S.%f%z")
    except ValueError as exc:
        raise _blocked(f"{field} has an invalid source timestamp") from exc
    return parsed.replace(tzinfo=UTC)


def _decimal(value: object, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise _blocked(f"{field} is not numeric") from exc
    if not result.is_finite():
        raise _blocked(f"{field} is not finite")
    return result


def validate_bar_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    timeframe: str = "1h",
    expected_count: int | None = None,
) -> tuple[CausalBarView, ...]:
    """Validate source-like rows and construct canonical closed bars."""

    if isinstance(rows, (str, bytes)) or not isinstance(rows, Sequence):
        raise _blocked("source rows must be a sequence")
    if expected_count is not None and len(rows) != expected_count:
        raise _blocked(f"source row count mismatch: {len(rows)}")
    bars: list[CausalBarView] = []
    previous_open: datetime | None = None
    expected_close_delta = timedelta(minutes=59, seconds=59, milliseconds=999)
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise _blocked(f"source row {index} is not a mapping")
        if set(row) != set(EXPECTED_SOURCE_HEADER):
            raise _blocked(f"source row {index} does not match the exact schema")
        opened_at = _source_datetime(row["open_time"], f"row {index}.open_time")
        source_closed_at = _source_close_datetime(
            row["close_time"], f"row {index}.close_time"
        )
        if source_closed_at != opened_at + expected_close_delta:
            raise _blocked(
                f"row {index}.close_time is inconsistent with Binance bar semantics"
            )
        if previous_open is not None and opened_at != previous_open + timedelta(
            hours=1
        ):
            raise _blocked(
                f"source timestamp grid has a gap, duplicate, or ordering error at row {index}"
            )
        previous_open = opened_at
        opened = _decimal(row["open"], f"row {index}.open")
        high = _decimal(row["high"], f"row {index}.high")
        low = _decimal(row["low"], f"row {index}.low")
        close = _decimal(row["close"], f"row {index}.close")
        volume = _decimal(row["volume"], f"row {index}.volume")
        taker_buy = _decimal(row["taker_buy_base"], f"row {index}.taker_buy_base")
        if min(opened, high, low, close) <= 0:
            raise _blocked(f"row {index} OHLC values must be positive")
        if volume < 0 or taker_buy < 0 or taker_buy > volume:
            raise _blocked(f"row {index} volume values are invalid")
        if low > high or not low <= opened <= high or not low <= close <= high:
            raise _blocked(f"row {index} OHLC geometry is invalid")
        closed_at = opened_at + timedelta(hours=1)
        bars.append(
            CausalBarView(
                timeframe=timeframe,
                bar_open_at=opened_at,
                bar_close_at=closed_at,
                market_as_of=closed_at,
                open=opened,
                high=high,
                low=low,
                close=close,
                volume=volume,
                taker_buy_base=taker_buy,
                closed=True,
            )
        )
    return tuple(bars)


@dataclass(frozen=True, slots=True)
class SourceData:
    bars: tuple[CausalBarView, ...]
    sha256: str
    header: tuple[str, ...]


def load_source(config: StudyConfig) -> SourceData:
    """Load and independently validate the frozen local source only."""

    if not config.source_path.is_file():
        raise _blocked(f"frozen study source is missing: {config.source_path}")
    actual_sha = sha256_file(config.source_path)
    if actual_sha != config.source_sha256:
        raise _blocked("STUDY_BLOCKED_SOURCE: frozen source SHA-256 mismatch")
    try:
        with config.source_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if tuple(reader.fieldnames or ()) != EXPECTED_SOURCE_HEADER:
                raise _blocked(
                    "source header does not match the exact 12-column schema"
                )
            rows = tuple(reader)
    except (OSError, csv.Error) as exc:
        raise _blocked(f"cannot read frozen source: {exc}") from exc
    if len(rows) != config.source_row_count:
        raise _blocked("STUDY_BLOCKED_SOURCE: frozen source row count mismatch")
    bars = validate_bar_rows(rows, expected_count=config.source_row_count)
    if not bars:
        raise _blocked("frozen source is empty")
    if (
        bars[0].bar_open_at != config.first_open_time
        or bars[-1].bar_open_at != config.last_open_time
        or bars[-1].bar_close_at != config.source_end
    ):
        raise _blocked("source temporal coverage does not match the predeclared source")
    return SourceData(bars=bars, sha256=actual_sha, header=EXPECTED_SOURCE_HEADER)


@dataclass(slots=True)
class ReplayGraph:
    config: Any
    composition: Any
    lane: Any
    feature_plan: Any
    data_plan: Any
    requirements: Any
    bar_store: BarStore
    runtime: ModelRuntime
    view_builder: DecisionViewBuilder
    key: MarketSeriesKey
    binding_by_slot: Mapping[str, Any]
    identity: Mapping[str, Any]
    history_max: int = 0

    async def observe(self, bar: CausalBarView) -> Mapping[str, Any]:
        self.bar_store.append(self.key, bar)
        retained = self.bar_store.retained_count(self.key)
        self.history_max = max(self.history_max, retained)
        view = self.view_builder.build_direct(
            self.lane,
            self.requirements,
            bar.market_as_of,
        )
        prepared = await self.runtime.prepare_live(
            view,
            resolver_knowledge_cutoff=bar.market_as_of,
        )
        results_by_slot: dict[str, Any] = {}
        by_id = {binding.binding_id: binding for binding in self.lane.bindings.values()}
        for binding_id, result in prepared.binding_results.items():
            results_by_slot[by_id[binding_id].slot_name] = result
        observer_result = results_by_slot.get("observer")
        primary_result = results_by_slot.get("primary")
        if observer_result is None or primary_result is None:
            raise _blocked(
                "R3B graph bindings are not the approved primary/observer pair"
            )
        observer_artifact = (
            observer_result.outcome.artifact
            if observer_result.status == "EXECUTED"
            and observer_result.outcome is not None
            else None
        )
        primary_artifact = (
            primary_result.outcome.artifact
            if primary_result.status == "EXECUTED"
            and primary_result.outcome is not None
            else None
        )
        return {
            "primary_status": primary_result.status,
            "observer_status": observer_result.status,
            "primary_artifact": primary_artifact,
            "observer_artifact": observer_artifact,
            "retained_count": retained,
            "market_as_of": bar.market_as_of,
        }


def _profile_identity(binding: Any, lane: Any) -> Mapping[str, Any]:
    from apps.decision_app.features.momentum_integration import (
        parse_momentum_binding_parameters,
    )

    profile = parse_momentum_binding_parameters(
        binding.parameters,
        expected_asset=lane.asset,
        expected_decision_timeframe=lane.decision_timeframe,
    )
    return {
        "asset": profile.asset,
        "decision_timeframe": profile.decision_timeframe,
        "model": profile.model_config.to_mapping(),
        "feature_profile": profile.feature_profile.to_mapping(),
        "m3_artifact_sha256": profile.m3_artifact_sha256,
        "route_profile_sha256": profile.route_profile_sha256,
    }


def build_replay_graph(study: StudyConfig) -> ReplayGraph:
    """Compile exactly the approved R3B graph and no research substitute."""

    global_fixture = (
        ROOT / "tests/decision/fixtures/regression_r3b/global.yaml"
    ).resolve()
    btc_fixture = (
        ROOT / "tests/decision/fixtures/regression_r3b/assets/BTC.yaml"
    ).resolve()
    if (
        sha256_file(global_fixture) != EXPECTED_GLOBAL_SHA
        or sha256_file(btc_fixture) != EXPECTED_BTC_SHA
    ):
        raise _blocked("STUDY_BLOCKED_RUNTIME_PARITY: R3B fixture hash drift")
    ConfigManager.reset_singleton()
    manager = ConfigManager(config_dir=str(ROOT / "configs"))
    try:
        decision_config = load_decision_config(
            manager,
            global_file=global_fixture,
            assets_directory=btc_fixture.parent,
        )
    finally:
        manager.shutdown()
        ConfigManager.reset_singleton()
    composition = build_production_composition(decision_config)
    decision_plan = compile_decision_plan(
        composition.plugin_catalog,
        decision_config.lane_specs(),
    )
    if len(decision_plan.lanes) != 1:
        raise _blocked("R3B fixture must resolve exactly one study lane")
    lane = decision_plan.lanes[0]
    if (
        lane.asset,
        lane.decision_timeframe,
        lane.trigger_timeframe,
        lane.authority,
    ) != (
        "BTCUSDT",
        "1h",
        "1h",
        "shadow",
    ):
        raise _blocked("R3B lane identity or authority drifted")
    if (lane.policy_name, lane.policy_version) != ("passthrough", "1"):
        raise _blocked("R3B policy is not passthrough@1")
    bindings_by_slot = {
        binding.slot_name: binding for binding in lane.bindings.values()
    }
    if set(bindings_by_slot) != {"primary", "observer"}:
        raise _blocked("R3B binding slots drifted")
    primary = bindings_by_slot["primary"]
    observer = bindings_by_slot["observer"]
    if (primary.plugin_name, primary.plugin_version) != ("momentum", "1"):
        raise _blocked("R3B primary provider is not momentum@1")
    if (observer.plugin_name, observer.plugin_version) != (
        "momentum_regression_observer",
        "1",
    ):
        raise _blocked("R3B observer plugin identity drifted")
    if observer.dependencies.get("momentum") != primary.binding_id:
        raise _blocked("R3B observer does not depend on the primary Momentum binding")
    if lane.policy_parameters.get("source_slot") != "primary":
        raise _blocked("R3B policy source_slot is not primary")
    slot_by_id = {
        binding.binding_id: binding.slot_name for binding in lane.bindings.values()
    }
    if tuple(slot_by_id[binding_id] for binding_id in lane.execution_order) != (
        "primary",
        "observer",
    ):
        raise _blocked("R3B execution order does not place Momentum before observer")

    feature_plan = compile_feature_plan(
        lane,
        composition.feature_catalog,
        composition.feature_policy,
        decision_config.timeframe_grid,
    )
    data_plan = compile_data_plan(
        lane,
        composition.data_policy,
        composition.data_source_catalog,
    )
    requirements = compile_lane_market_requirements(
        lane, decision_config.timeframe_grid
    )
    capacities = merge_bar_store_capacities(
        compile_bar_store_capacities(decision_plan, decision_config.timeframe_grid),
        compile_feature_bar_store_capacities(
            decision_plan,
            {lane.lane_id: feature_plan},
            composition.feature_catalog,
            decision_config.timeframe_grid,
        ),
    )
    if len(capacities) != 1 or max(capacities.values()) != 136:
        raise _blocked("R3B compiled history capacity is not exactly 136 bars")
    key = requirements.decision_series
    bar_store = BarStore(capacities)
    runtime = ModelRuntime(
        lane,
        feature_plan,
        data_plan,
        FeatureEngine(
            composition.feature_catalog, bar_store, decision_config.timeframe_grid
        ),
        composition.data_resolver,
        composition.runtime_plugin_catalog,
        decision_config.timeframe_grid,
    )
    feature_config_fingerprint = feature_plan.feature_config_fingerprints.get(
        "REGRESSION_CONTEXT"
    )
    if (
        not isinstance(feature_config_fingerprint, str)
        or not feature_config_fingerprint
    ):
        raise _blocked("REGRESSION_CONTEXT feature fingerprint is unavailable")
    identity = {
        "lane_id": lane.lane_id,
        "asset": lane.asset,
        "decision_timeframe": lane.decision_timeframe,
        "trigger_timeframe": lane.trigger_timeframe,
        "authority": lane.authority,
        "policy": {
            "name": lane.policy_name,
            "version": lane.policy_version,
            "source_slot": lane.policy_parameters["source_slot"],
        },
        "execution_order": [slot_by_id[item] for item in lane.execution_order],
        "bindings": {
            slot: {
                "plugin": f"{binding.plugin_name}@{binding.plugin_version}",
                "binding_id": binding.binding_id,
                "dependencies": dict(binding.dependencies),
            }
            for slot, binding in sorted(bindings_by_slot.items())
        },
        "momentum_profile": _profile_identity(primary, lane),
        "momentum_model_spec": {
            "name": MOMENTUM_MODEL_SPEC.name,
            "version": MOMENTUM_MODEL_SPEC.version,
            "artifact_type": MOMENTUM_MODEL_SPEC.produces_artifact_type,
        },
        "observer_artifact_type": MOMENTUM_REGRESSION_OBSERVATION_ARTIFACT_TYPE,
        "feature_plan_fingerprint": feature_plan.feature_plan_fingerprint,
        "feature_config_fingerprint": feature_config_fingerprint,
        "compiled_history_capacity": max(capacities.values()),
        "feature_history_requirements": {
            name: {
                timeframe: count
                for key, count in history.items()
                for timeframe in [key.timeframe]
            }
            for name, history in sorted(feature_plan.history_requirements.items())
        },
    }
    return ReplayGraph(
        config=decision_config,
        composition=composition,
        lane=lane,
        feature_plan=feature_plan,
        data_plan=data_plan,
        requirements=requirements,
        bar_store=bar_store,
        runtime=runtime,
        view_builder=DecisionViewBuilder(bar_store, decision_config.timeframe_grid),
        key=key,
        binding_by_slot=bindings_by_slot,
        identity=identity,
    )


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw(item) for item in value]
    if isinstance(value, datetime):
        return _iso(value)
    if isinstance(value, Decimal):
        return float(value)
    return value


def _artifact_payload(result: Mapping[str, Any]) -> Mapping[str, Any] | None:
    artifact = result["observer_artifact"]
    if artifact is None:
        return None
    if result["primary_artifact"] is None:
        raise _blocked("observer executed without its primary Momentum artifact")
    if artifact.artifact_type != MOMENTUM_REGRESSION_OBSERVATION_ARTIFACT_TYPE:
        raise _blocked("observer returned an unexpected artifact type")
    value = _thaw(artifact.value)
    provenance = _thaw(artifact.provenance)
    if not isinstance(value, Mapping) or not isinstance(provenance, Mapping):
        raise _blocked("observer artifact shape is not a mapping")
    if provenance.get("momentum_artifact_type") != "momentum.signal.v1":
        raise _blocked("observer did not receive momentum.signal.v1")
    if not isinstance(result["primary_artifact"].value, Mapping):
        raise _blocked("primary Momentum artifact is not a mapping")
    if provenance.get("momentum_binding_id") != result["primary_artifact"].binding_id:
        raise _blocked(
            "observer provenance does not identify the real primary artifact"
        )
    return {"value": value, "provenance": provenance}


def _fold_for(value: datetime, study: StudyConfig) -> str | None:
    for name in EXPECTED_FOLDS:
        start, end = study.folds[name]
        if start <= value < end:
            return name
    return None


def _outcome(
    bars: Sequence[CausalBarView],
    index: int,
    horizon: int,
    direction: int,
) -> Mapping[str, Any]:
    current = float(bars[index].close)
    future = bars[index + 1 : index + horizon + 1]
    forward = math.log(float(future[-1].close) / current)
    if direction == 0:
        aligned = None
        favorable = None
        adverse = None
        continuation = None
    elif direction == 1:
        aligned = forward
        favorable = max(0.0, max(math.log(float(bar.high) / current) for bar in future))
        adverse = max(0.0, max(math.log(current / float(bar.low)) for bar in future))
        continuation = aligned > 0.0
    elif direction == -1:
        aligned = -forward
        favorable = max(0.0, max(math.log(current / float(bar.low)) for bar in future))
        adverse = max(0.0, max(math.log(float(bar.high) / current) for bar in future))
        continuation = aligned > 0.0
    else:
        raise ValueError("direction must be -1, 0, or 1")
    return {
        "forward_log_return": forward,
        "aligned_log_return": aligned,
        "favorable_excursion_log": favorable,
        "adverse_excursion_log": adverse,
        "continuation": continuation,
    }


def _record(
    index: int,
    bar: CausalBarView,
    fold: str,
    artifact: Mapping[str, Any],
    bars: Sequence[CausalBarView],
    horizons: Sequence[int],
) -> Mapping[str, Any]:
    value = artifact["value"]
    provenance = artifact["provenance"]
    momentum = value["momentum"]
    regression = value["regression"]
    direction = int(momentum["direction"])
    record = {
        "identity": {
            "market_as_of": _iso(bar.market_as_of),
            "bar_open_at": _iso(bar.bar_open_at),
            "fold": fold,
            "source_row_index": index,
        },
        "momentum": {
            "direction": direction,
            "conviction": float(momentum["conviction"]),
            "score": float(momentum["score"]),
        },
        "regression": {
            "slope_log_per_hour": float(regression["slope_log_per_hour"]),
            "fit_quality": float(regression["fit_quality"]),
            "region": regression["region"],
            "outer_channel_position": float(regression["outer_channel_position"]),
            "outer_width_fraction": float(regression["outer_width_fraction"]),
            "upper_outer_breach": bool(regression["upper_outer_breach"]),
            "lower_outer_breach": bool(regression["lower_outer_breach"]),
            "previous_region": regression["previous_region"],
            "reentered_from_upper_outer": regression["reentered_from_upper_outer"],
            "reentered_from_lower_outer": regression["reentered_from_lower_outer"],
        },
        "regression_provenance": {
            "feature_config_fingerprint": provenance[
                "regression_feature_config_fingerprint"
            ],
            "source_config_hash": provenance["regression_source_config_hash"],
            "channel_config_hash": provenance["regression_channel_config_hash"],
            "context_id": provenance["regression_context_id"],
        },
        "outcomes": {
            str(horizon): _outcome(bars, index, horizon, direction)
            for horizon in horizons
        },
    }
    canonical_json_bytes(record)
    return record


def _direction_name(direction: int | str) -> str:
    if direction in (1, "long"):
        return "long"
    if direction in (-1, "short"):
        return "short"
    if direction in (0, "neutral"):
        return "neutral"
    if direction == "combined":
        return "combined"
    raise ValueError(f"unsupported direction {direction}")


def _metric_value(value: object) -> float | None:
    if value is None:
        return None
    result = float(value)
    if not math.isfinite(result):
        raise _blocked("non-finite metric input")
    return result


def _mean(values: Sequence[float]) -> float | None:
    return None if not values else float(statistics.fmean(values))


def _median(values: Sequence[float]) -> float | None:
    return None if not values else float(statistics.median(values))


def _summary(rows: Sequence[Mapping[str, Any]], horizon: int) -> Mapping[str, Any]:
    aligned: list[float] = []
    favorable: list[float] = []
    adverse: list[float] = []
    continuations: list[bool] = []
    convictions: list[float] = []
    key = str(horizon)
    for row in rows:
        outcome = row["outcomes"][key]
        if outcome["aligned_log_return"] is None:
            raise _blocked("directional metric received a neutral outcome")
        aligned.append(_metric_value(outcome["aligned_log_return"]) or 0.0)
        favorable.append(_metric_value(outcome["favorable_excursion_log"]) or 0.0)
        adverse.append(_metric_value(outcome["adverse_excursion_log"]) or 0.0)
        continuations.append(bool(outcome["continuation"]))
        convictions.append(_metric_value(row["momentum"]["conviction"]) or 0.0)
    return {
        "count": len(rows),
        "mean_aligned_log_return": _mean(aligned),
        "median_aligned_log_return": _median(aligned),
        "continuation_rate": (
            None if not continuations else sum(continuations) / len(continuations)
        ),
        "mean_favorable_excursion_log": _mean(favorable),
        "median_favorable_excursion_log": _median(favorable),
        "mean_adverse_excursion_log": _mean(adverse),
        "median_adverse_excursion_log": _median(adverse),
        "mean_momentum_conviction": _mean(convictions),
    }


def _delta(group: Mapping[str, Any], baseline: Mapping[str, Any]) -> Mapping[str, Any]:
    result: dict[str, Any] = {}
    for field in METRIC_FIELDS:
        left = group[field]
        right = baseline[field]
        result[field] = None if left is None or right is None else left - right
    return result


def _rows_for(
    rows: Sequence[Mapping[str, Any]],
    *,
    fold: str | None = None,
    direction: str,
    horizon: int,
    year: int | None = None,
) -> list[Mapping[str, Any]]:
    result: list[Mapping[str, Any]] = []
    for row in rows:
        if fold is not None and row["identity"]["fold"] != fold:
            continue
        if year is not None:
            timestamp = row["identity"]["market_as_of"]
            if int(timestamp[0:4]) != year:
                continue
        row_direction = int(row["momentum"]["direction"])
        if direction == "long" and row_direction != 1:
            continue
        if direction == "short" and row_direction != -1:
            continue
        if direction == "combined" and row_direction not in {-1, 1}:
            continue
        if row["outcomes"][str(horizon)]["aligned_log_return"] is None:
            continue
        result.append(row)
    return result


def _group_sort_key(value: object) -> tuple[int, str]:
    return (0 if value is None else 1, "" if value is None else str(value))


def _rank(values: Sequence[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start + 1
        while end < len(order) and values[order[end]] == values[order[start]]:
            end += 1
        rank = (start + 1 + end) / 2.0
        for position in range(start, end):
            ranks[order[position]] = rank
        start = end
    return ranks


def spearman_rho(x_values: Sequence[float], y_values: Sequence[float]) -> float | None:
    """Return tie-aware Spearman rho without a p-value or IID claim."""

    if len(x_values) != len(y_values):
        raise ValueError("Spearman inputs must have equal length")
    if len(x_values) < 2:
        return None
    if any(not math.isfinite(float(value)) for value in (*x_values, *y_values)):
        raise _blocked("continuous rank metric received non-finite data")
    x_rank = _rank([float(value) for value in x_values])
    y_rank = _rank([float(value) for value in y_values])
    x_mean = statistics.fmean(x_rank)
    y_mean = statistics.fmean(y_rank)
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_rank, y_rank))
    x_scale = math.sqrt(sum((x - x_mean) ** 2 for x in x_rank))
    y_scale = math.sqrt(sum((y - y_mean) ** 2 for y in y_rank))
    if x_scale == 0.0 or y_scale == 0.0:
        return None
    return numerator / (x_scale * y_scale)


def _conditional_metrics(
    rows: Sequence[Mapping[str, Any]], study: StudyConfig
) -> Mapping[str, Any]:
    directions = ("long", "short", "combined")
    baseline: dict[str, Any] = {}
    categorical: dict[str, Any] = {field: {} for field in CATEGORICAL_FIELDS}
    continuous: dict[str, Any] = {field: {} for field in CONTINUOUS_FIELDS}
    for fold in EXPECTED_FOLDS:
        baseline[fold] = {}
        for direction in directions:
            baseline[fold][direction] = {}
            for horizon in study.horizons:
                selected = _rows_for(
                    rows,
                    fold=fold,
                    direction=direction,
                    horizon=horizon,
                )
                base_summary = _summary(selected, horizon)
                baseline[fold][direction][str(horizon)] = base_summary
                for field in CATEGORICAL_FIELDS:
                    categorical[field].setdefault(fold, {}).setdefault(direction, {})[
                        str(horizon)
                    ] = {
                        "baseline": base_summary,
                        "groups": [
                            {
                                "value": value,
                                "metrics": _summary(
                                    [
                                        row
                                        for row in selected
                                        if row["regression"][field] == value
                                    ],
                                    horizon,
                                ),
                                "delta_vs_matching_momentum_baseline": _delta(
                                    _summary(
                                        [
                                            row
                                            for row in selected
                                            if row["regression"][field] == value
                                        ],
                                        horizon,
                                    ),
                                    base_summary,
                                ),
                            }
                            for value in sorted(
                                {row["regression"][field] for row in selected},
                                key=_group_sort_key,
                            )
                        ],
                    }
                for field in CONTINUOUS_FIELDS:
                    x_values = [float(row["regression"][field]) for row in selected]
                    y_values = [
                        float(row["outcomes"][str(horizon)]["aligned_log_return"])
                        for row in selected
                    ]
                    continuous[field].setdefault(fold, {}).setdefault(direction, {})[
                        str(horizon)
                    ] = {
                        "sample_count": len(selected),
                        "spearman_rho": spearman_rho(x_values, y_values),
                    }

    calendar: dict[str, Any] = {}
    for year in (2022, 2023, 2024, 2025, 2026):
        year_key = str(year)
        calendar[year_key] = {}
        for direction in directions:
            calendar[year_key][direction] = {
                str(horizon): _summary(
                    _rows_for(rows, direction=direction, horizon=horizon, year=year),
                    horizon,
                )
                for horizon in study.horizons
            }
    return {
        "study_id": study.raw["study"]["id"],
        "horizons": list(study.horizons),
        "folds": list(EXPECTED_FOLDS),
        "baseline": baseline,
        "categorical": categorical,
        "continuous": continuous,
        "calendar_year": calendar,
        "statistical_claims": {
            "iid_p_values": False,
            "overlap_aware_inference": False,
            "threshold_optimization": False,
        },
    }


def _canonical_artifact_observation(payload: Mapping[str, Any]) -> bytes:
    return canonical_json_bytes(payload)


async def _run_prefix(
    study: StudyConfig,
    bars: Sequence[CausalBarView],
    through_index: int,
) -> Mapping[str, Any]:
    graph = build_replay_graph(study)
    final: Mapping[str, Any] | None = None
    for bar in bars[: through_index + 1]:
        final = await graph.observe(bar)
    if final is None:
        raise _blocked("causality probe did not replay any bar")
    payload = _artifact_payload(final)
    return {
        "artifact": payload,
        "artifact_bytes": None
        if payload is None
        else _canonical_artifact_observation(payload).hex(),
        "retained_count": graph.bar_store.retained_count(graph.key),
        "history_max": graph.history_max,
        "last_cutoff": _iso(bars[through_index].market_as_of),
    }


async def _causality_probe(
    study: StudyConfig, bars: Sequence[CausalBarView]
) -> Mapping[str, Any]:
    cutoff_index = 135
    original = await _run_prefix(study, bars, cutoff_index)
    mutated_bars = list(bars)
    factor = Decimal(2)
    for index in range(cutoff_index + 1, len(mutated_bars)):
        bar = mutated_bars[index]
        mutated_bars[index] = replace(
            bar,
            open=bar.open * factor,
            high=bar.high * factor,
            low=bar.low * factor,
            close=bar.close * factor,
            volume=bar.volume * factor,
            taker_buy_base=(
                None if bar.taker_buy_base is None else bar.taker_buy_base * factor
            ),
        )
    mutated = await _run_prefix(study, mutated_bars, cutoff_index)
    if original["artifact_bytes"] != mutated["artifact_bytes"]:
        raise _blocked("STUDY_BLOCKED_CAUSALITY: future suffix changed the observation")
    original_label = _outcome(bars, cutoff_index, 1, 1)["forward_log_return"]
    mutated_label = _outcome(mutated_bars, cutoff_index, 1, 1)["forward_log_return"]
    if original_label == mutated_label:
        raise _blocked(
            "future suffix mutation did not change the expected future label"
        )
    return {
        "cutoff_source_row_index": cutoff_index,
        "observation_prefix_rows": cutoff_index + 1,
        "future_ohlcv_mutated_after_cutoff": all(
            (
                bars[index].open != mutated_bars[index].open
                and bars[index].high != mutated_bars[index].high
                and bars[index].low != mutated_bars[index].low
                and bars[index].close != mutated_bars[index].close
                and bars[index].volume != mutated_bars[index].volume
            )
            for index in range(cutoff_index + 1, len(bars))
        ),
        "observation_byte_identical": True,
        "future_label_changed": True,
        "original_forward_log_return_h1": original_label,
        "mutated_forward_log_return_h1": mutated_label,
        "original_history_max": original["history_max"],
        "mutated_history_max": mutated["history_max"],
        "original_retained_count": original["retained_count"],
        "mutated_retained_count": mutated["retained_count"],
        "observation_cutoff": original["last_cutoff"],
    }


def _status_paths(root: Path) -> tuple[str, ...]:
    output = subprocess.run(
        ["git", "status", "--short", "--untracked-files=all"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    paths: list[str] = []
    for line in output:
        if not line:
            continue
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if path.startswith('"'):
            path = json.loads(path)
        paths.append(path)
    return tuple(sorted(set(paths)))


def canonical_worktree_manifest(
    root: Path,
    *,
    excluded_prefixes: Sequence[str] = (),
) -> tuple[tuple[Mapping[str, Any], ...], str]:
    records: list[Mapping[str, Any]] = []
    for relative in _status_paths(root):
        if any(
            relative == prefix or relative.startswith(prefix)
            for prefix in excluded_prefixes
        ):
            continue
        path = root / relative
        if path.is_file():
            records.append(
                {
                    "path": relative,
                    "state": "file",
                    "sha256": sha256_file(path),
                }
            )
        else:
            records.append({"path": relative, "state": "deleted"})
    ordered = tuple(sorted(records, key=lambda item: str(item["path"])))
    return ordered, sha256_bytes(canonical_json_bytes(ordered))


def _preserved_manifests(root: Path) -> Mapping[str, Any]:
    excluded = R3C1_PATH_PREFIXES
    cumulative_records, cumulative_hash = canonical_worktree_manifest(
        root,
        excluded_prefixes=excluded,
    )
    r3p_records, r3p_hash = canonical_worktree_manifest(
        root,
        excluded_prefixes=(*excluded, *R3B_ONLY_PATHS),
    )
    if (len(cumulative_records), cumulative_hash) != (84, EXPECTED_CUMULATIVE_MANIFEST):
        raise _blocked(
            "pre-R3C1 cumulative manifest changed: "
            f"records={len(cumulative_records)} sha256={cumulative_hash}"
        )
    if (len(r3p_records), r3p_hash) != (77, EXPECTED_R3P_MANIFEST):
        raise _blocked(
            f"R3P manifest changed: records={len(r3p_records)} sha256={r3p_hash}"
        )
    return {
        "cumulative": {
            "record_count": len(cumulative_records),
            "file_count": sum(item["state"] == "file" for item in cumulative_records),
            "deletion_count": sum(
                item["state"] == "deleted" for item in cumulative_records
            ),
            "sha256": cumulative_hash,
        },
        "r3p": {
            "record_count": len(r3p_records),
            "file_count": sum(item["state"] == "file" for item in r3p_records),
            "deletion_count": sum(item["state"] == "deleted" for item in r3p_records),
            "sha256": r3p_hash,
        },
    }


def _json_write(path: Path, value: object) -> None:
    path.write_bytes(canonical_json_bytes(value) + b"\n")


def verify_artifacts(root: Path) -> Mapping[str, Any]:
    """Verify the deterministic checksum file and all expected members."""

    checksums_path = root / "checksums.json"
    if not checksums_path.is_file():
        raise _blocked("checksums.json is missing")
    checksums = json.loads(checksums_path.read_text(encoding="utf-8"))
    if set(checksums) != {"algorithm", "files"} or checksums["algorithm"] != "sha256":
        raise _blocked("checksums.json shape is invalid")
    files = checksums["files"]
    if set(files) != set(EXPECTED_ARTIFACT_NAMES) - {"checksums.json"}:
        raise _blocked("checksums.json does not cover exactly the non-self artifacts")
    for name, expected in sorted(files.items()):
        path = root / name
        if not path.is_file() or sha256_file(path) != expected:
            raise _blocked(f"artifact checksum mismatch: {name}")
    return {"verified": True, "covered_files": len(files)}


def _coverage_summary(
    study: StudyConfig,
    source: SourceData,
    graph: ReplayGraph,
    records: Sequence[Mapping[str, Any]],
    causality: Mapping[str, Any],
    preserved: Mapping[str, Any],
) -> Mapping[str, Any]:
    by_fold: dict[str, Any] = {}
    for fold in EXPECTED_FOLDS:
        selected = [row for row in records if row["identity"]["fold"] == fold]
        by_fold[fold] = {
            "eligible_count": len(selected),
            "long_count": sum(row["momentum"]["direction"] == 1 for row in selected),
            "short_count": sum(row["momentum"]["direction"] == -1 for row in selected),
            "neutral_count": sum(row["momentum"]["direction"] == 0 for row in selected),
        }
    return {
        "status": "STUDY_COMPLETE",
        "source": {
            "path": str(study.source_path.relative_to(ROOT)),
            "sha256": source.sha256,
            "row_count": len(source.bars),
            "header": list(source.header),
            "first_open_time": _iso(source.bars[0].bar_open_at),
            "last_open_time": _iso(source.bars[-1].bar_open_at),
            "first_market_as_of": _iso(source.bars[0].market_as_of),
            "last_market_as_of": _iso(source.bars[-1].market_as_of),
            "source_end": _iso(study.source_end),
            "provider_or_network_fallback": False,
        },
        "population": {
            "eligible_observation_count": len(records),
            "long_count": sum(row["momentum"]["direction"] == 1 for row in records),
            "short_count": sum(row["momentum"]["direction"] == -1 for row in records),
            "neutral_count": sum(row["momentum"]["direction"] == 0 for row in records),
            "all_eligible_momentum_outputs_recorded": True,
            "first_full_history_source_row_index": 135,
            "maximum_outcome_horizon": max(study.horizons),
            "folds": list(EXPECTED_FOLDS),
            "horizons": list(study.horizons),
        },
        "label_separation": {
            "attached_after_causal_observation": True,
            "future_bars_supplied_to_decision_graph": False,
            "fold_horizon_boundary_violations": 0,
        },
        "by_fold": by_fold,
        "runtime": {
            "graph": graph.identity,
            "history_max": graph.history_max,
            "history_capacity_bound": 136,
            "publication_called": False,
            "signal_envelope_built": False,
        },
        "causality": causality,
        "preserved_manifests": preserved,
        "study_config_digest": study.semantic_digest,
    }


def _summary_markdown(
    study: StudyConfig,
    source: SourceData,
    records: Sequence[Mapping[str, Any]],
    metrics: Mapping[str, Any],
    coverage: Mapping[str, Any],
) -> str:
    holdout = metrics["baseline"]["holdout"]["combined"]["1"]
    holdout_16 = metrics["baseline"]["holdout"]["combined"]["16"]
    holdout_region_groups = metrics["categorical"]["region"]["holdout"]["combined"][
        "1"
    ]["groups"]
    non_null_rhos = sum(
        metrics["continuous"][field]["holdout"]["combined"]["1"]["spearman_rho"]
        is not None
        for field in CONTINUOUS_FIELDS
    )
    return "\n".join(
        (
            "# R3C1 BTCUSDT/1h Momentum Context Utility",
            "",
            "Status: `STUDY_COMPLETE`",
            "",
            "This is a deterministic, point-in-time descriptive study. It does not",
            "select thresholds, define a trading rule, report IID significance, or",
            "recommend a runtime change.",
            "",
            f"- Source: `{study.source_path.relative_to(ROOT)}`",
            f"- Source SHA-256: `{source.sha256}`",
            f"- Source rows: `{len(source.bars)}`",
            f"- Eligible observations: `{len(records)}`",
            f"- Folds: `{', '.join(EXPECTED_FOLDS)}`",
            f"- Horizons: `{list(study.horizons)}`",
            "",
            "## Fixed descriptive reference points",
            "",
            (
                f"- Holdout combined directional h=1: n={holdout['count']}, "
                f"mean aligned log return={holdout['mean_aligned_log_return']}, "
                f"continuation rate={holdout['continuation_rate']}"
            ),
            (
                f"- Holdout combined directional h=16: n={holdout_16['count']}, "
                f"mean aligned log return={holdout_16['mean_aligned_log_return']}, "
                f"continuation rate={holdout_16['continuation_rate']}"
            ),
            f"- Holdout h=1 region groups observed: `{len(holdout_region_groups)}`",
            f"- Holdout h=1 continuous fields with defined Spearman rho: `{non_null_rhos}/4`",
            "",
            "## Integrity",
            "",
            f"- Bounded Decision history maximum: `{coverage['runtime']['history_max']}`",
            f"- Future-suffix observation unchanged: `{coverage['causality']['observation_byte_identical']}`",
            f"- Future label changed under suffix mutation: `{coverage['causality']['future_label_changed']}`",
            f"- Cumulative runtime manifest: `{coverage['preserved_manifests']['cumulative']['sha256']}`",
            f"- R3P manifest: `{coverage['preserved_manifests']['r3p']['sha256']}`",
            "",
            "No promotion disposition is emitted by this study.",
            "",
        )
    )


def write_artifacts(
    study: StudyConfig,
    source: SourceData,
    graph: ReplayGraph,
    records: Sequence[Mapping[str, Any]],
    causality: Mapping[str, Any],
    preserved: Mapping[str, Any],
) -> Mapping[str, Any]:
    output = study.output_root
    output.mkdir(parents=True, exist_ok=True)
    metrics = _conditional_metrics(records, study)
    coverage = _coverage_summary(study, source, graph, records, causality, preserved)
    source_identity = {
        "validator": "r3c1_frozen_binance_ohlcv_v1",
        "path": str(study.source_path.relative_to(ROOT)),
        "sha256": source.sha256,
        "header": list(source.header),
        "row_count": len(source.bars),
        "asset": study.source_asset,
        "timeframe": study.source_timeframe,
        "first_open_time": _iso(source.bars[0].bar_open_at),
        "last_open_time": _iso(source.bars[-1].bar_open_at),
        "first_market_as_of": _iso(source.bars[0].market_as_of),
        "last_market_as_of": _iso(source.bars[-1].market_as_of),
        "source_end": _iso(study.source_end),
        "contiguous_one_hour_grid": True,
        "duplicate_timestamps": False,
        "finite_positive_ohlc": True,
        "finite_non_negative_volume": True,
        "taker_buy_base_used": True,
        "decision_bar_close_rule": "bar_open_at + 1h",
        "source_close_time_used_as_decision_cutoff": False,
    }
    ledger_path = output / "observation_ledger.jsonl"
    ledger_path.write_bytes(
        b"".join(canonical_json_bytes(record) + b"\n" for record in records)
    )
    _json_write(output / "source_identity.json", source_identity)
    _json_write(output / "coverage_summary.json", coverage)
    _json_write(output / "conditional_metrics.json", metrics)
    summary = _summary_markdown(study, source, records, metrics, coverage)
    (output / "study_summary.md").write_text(summary, encoding="utf-8")

    member_hashes = {
        name: sha256_file(output / name)
        for name in EXPECTED_ARTIFACT_NAMES
        if name not in {"checksums.json", "study_manifest.json"}
    }
    study_manifest = {
        "status": "STUDY_COMPLETE",
        "study_identity": {
            "study_id": study.raw["study"]["id"],
            "study_version": study.raw["study"]["version"],
            "base_git_sha": EXPECTED_BASE_SHA,
            "pre_r3c1_cumulative_manifest_sha256": EXPECTED_CUMULATIVE_MANIFEST,
            "r3p_manifest_sha256": EXPECTED_R3P_MANIFEST,
            "source_sha256": source.sha256,
            "r3b_global_fixture_sha256": EXPECTED_GLOBAL_SHA,
            "r3b_btc_fixture_sha256": EXPECTED_BTC_SHA,
            "m3_artifact_sha256": EXPECTED_M3_SHA,
            "m4_artifact_sha256": EXPECTED_M4_SHA,
            "study_config_digest": study.semantic_digest,
            "loaded_graph": graph.identity,
            "regression_source_config_hash": EXPECTED_SOURCE_CONFIG_HASH,
            "regression_channel_config_hash": EXPECTED_CHANNEL_CONFIG_HASH,
            "regression_context_id": EXPECTED_CONTEXT_ID,
            "observer_plugin": "momentum_regression_observer@1",
            "observer_artifact_type": MOMENTUM_REGRESSION_OBSERVATION_ARTIFACT_TYPE,
        },
        "population": coverage["population"],
        "folds": study.raw["folds"],
        "outcome_horizons": list(study.horizons),
        "artifact_inventory": [
            {
                "path": name,
                "state": "file",
                **({"sha256": member_hashes[name]} if name in member_hashes else {}),
            }
            for name in EXPECTED_ARTIFACT_NAMES
        ],
        "member_sha256": member_hashes,
        "manifest_hashing_note": (
            "checksums.json covers every non-self artifact; a manifest cannot include "
            "its own digest without a circular fixed point"
        ),
    }
    _json_write(output / "study_manifest.json", study_manifest)
    checksum_files = {
        name: sha256_file(output / name)
        for name in EXPECTED_ARTIFACT_NAMES
        if name != "checksums.json"
    }
    _json_write(
        output / "checksums.json",
        {"algorithm": "sha256", "files": checksum_files},
    )
    verified = verify_artifacts(output)
    return {
        "output_root": str(output.relative_to(ROOT)),
        "observation_ledger_sha256": sha256_file(ledger_path),
        "conditional_metrics_sha256": sha256_file(output / "conditional_metrics.json"),
        "study_manifest_sha256": sha256_file(output / "study_manifest.json"),
        "checksums_sha256": sha256_file(output / "checksums.json"),
        "artifact_verification": verified,
    }


async def _run_replay(
    study: StudyConfig,
    source: SourceData,
) -> tuple[ReplayGraph, list[Mapping[str, Any]], Mapping[str, Any]]:
    graph = build_replay_graph(study)
    records: list[Mapping[str, Any]] = []
    first_ready_index: int | None = None
    before_warmup_observer = False
    provenance_identities: set[tuple[str, str, str, str]] = set()
    for index, bar in enumerate(source.bars):
        result = await graph.observe(bar)
        artifact_payload = _artifact_payload(result)
        if index < 135:
            if artifact_payload is not None:
                before_warmup_observer = True
            continue
        if artifact_payload is None:
            raise _blocked(
                f"STUDY_BLOCKED_RUNTIME_PARITY: no observer artifact at source row {index}"
            )
        if first_ready_index is None:
            first_ready_index = index
        provenance = artifact_payload["provenance"]
        provenance_identities.add(
            (
                provenance["regression_source_config_hash"],
                provenance["regression_channel_config_hash"],
                provenance["regression_context_id"],
                provenance["regression_feature_config_fingerprint"],
            )
        )
        fold = _fold_for(bar.market_as_of, study)
        max_index = index + max(study.horizons)
        if fold is None or max_index >= len(source.bars):
            continue
        fold_end = study.folds[fold][1]
        if source.bars[max_index].market_as_of >= fold_end:
            continue
        records.append(
            _record(index, bar, fold, artifact_payload, source.bars, study.horizons)
        )
    if before_warmup_observer or first_ready_index != 135:
        raise _blocked("full 136-bar history boundary was not enforced")
    if provenance_identities != {
        (
            EXPECTED_SOURCE_CONFIG_HASH,
            EXPECTED_CHANNEL_CONFIG_HASH,
            EXPECTED_CONTEXT_ID,
            graph.identity["feature_config_fingerprint"],
        )
    }:
        raise _blocked(
            "regression provenance identity changed during sequential replay"
        )
    if graph.history_max > 136:
        raise _blocked("Decision history exceeded the compiled 136-bar bound")
    if not records:
        raise _blocked("study produced no eligible observations")
    return (
        graph,
        records,
        {
            "first_ready_source_row_index": first_ready_index,
            "before_warmup_observer_artifact": before_warmup_observer,
            "all_runtime_observations_executed": True,
        },
    )


def run_study(study: StudyConfig | None = None) -> Mapping[str, Any]:
    study = study or load_study_config()
    if (
        subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        != EXPECTED_BASE_SHA
    ):
        raise _blocked("study worktree base SHA is not the approved current-main base")
    preserved_before = _preserved_manifests(ROOT)
    source = load_source(study)
    graph, records, replay_checks = asyncio.run(_run_replay(study, source))
    causality = asyncio.run(_causality_probe(study, source.bars))
    if (
        causality["original_history_max"] > 136
        or causality["mutated_history_max"] > 136
    ):
        raise _blocked("causality probe exceeded the 136-bar bound")
    preserved_after = _preserved_manifests(ROOT)
    if preserved_after != preserved_before:
        raise _blocked("pre-R3C1 runtime manifest changed during the study")
    result = write_artifacts(
        study,
        source,
        graph,
        records,
        causality,
        preserved_after,
    )
    result.update(
        {
            "source": {
                "path": str(study.source_path.relative_to(ROOT)),
                "sha256": source.sha256,
                "rows": len(source.bars),
                "first_open_time": _iso(source.bars[0].bar_open_at),
                "last_open_time": _iso(source.bars[-1].bar_open_at),
                "source_end": _iso(study.source_end),
            },
            "graph_identity": graph.identity,
            "replay_checks": replay_checks,
            "eligible_observations": len(records),
            "direction_counts": {
                name: sum(row["momentum"]["direction"] == direction for row in records)
                for name, direction in (("long", 1), ("short", -1), ("neutral", 0))
            },
            "fold_counts": {
                fold: sum(row["identity"]["fold"] == fold for row in records)
                for fold in EXPECTED_FOLDS
            },
            "horizons": list(study.horizons),
            "preserved_manifests": preserved_after,
            "terminal_status": "STUDY_COMPLETE",
        }
    )
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    args = parser.parse_args(argv)
    try:
        result = run_study(load_study_config(args.config))
    except StudyBlocked as exc:
        print(
            f"REGRESSION_R3C1_BTC1H_MOMENTUM_CONTEXT_UTILITY_BLOCKED: {exc}",
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    print("REGRESSION_R3C1_BTC1H_MOMENTUM_CONTEXT_UTILITY_STUDY_COMPLETE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
