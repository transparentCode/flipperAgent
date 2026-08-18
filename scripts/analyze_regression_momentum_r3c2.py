"""Deterministic R3C2 replication of the predeclared 4h short contrast.

This is research-only code.  It loads frozen local OHLCV members, transforms
the certified M4 4h route in memory into the approved R3B shadow graph, and
replays that graph causally through the public Decision seams.  It does not
implement Momentum or regression, acquire provider data, select another
feature, or emit a promotion disposition.
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
from collections import defaultdict
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
from apps.decision_app.planning.planner import compile_decision_plan
from apps.decision_app.planning.readiness import compile_lane_market_requirements
from apps.decision_app.runtime.models import ModelRuntime
from apps.decision_app.settings import (
    DecisionBindingSettings,
    DecisionConfig,
    FeaturePolicySettings,
    load_decision_config,
)
from libs.common.config import ConfigManager
from libs.contracts.decision import CausalBarView
from libs.regression.channel import (
    STRUCTURAL_CHANNEL_ID,
    channel_config_fingerprint,
)
from libs.regression.config.resolver import ConfigResolver
from libs.regression.context_snapshot import REGRESSION_CONTEXT_ID
from libs.regression.structural import STRUCTURAL_ESTIMATOR_ID

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = (
    ROOT
    / "research"
    / "regression_r3c"
    / "r3c2_4h_short_overextension_replication_v1.yaml"
)

EXPECTED_BASE_SHA = "4647a04dc53a7ffd3de85a2f84b10bae4be9cefa"
EXPECTED_CUMULATIVE_MANIFEST = (
    "2085c0f9cf290e763c97b016bb2ea38a2cc22559500d357cf475c2d085b017e0"
)
EXPECTED_R3P_MANIFEST = (
    "93f8c140560e5a5f6237fe4805e309ab07f3fdbcbd77b9bbd33f127d26dce8cc"
)
EXPECTED_M3_SHA = "6fcd3d736524b513a63f244a3268478a658924cd571a62a72ec33958ad67972c"
EXPECTED_M4_SHA = "3d1339be919e8d176dcd1053cb1c42f46bf6a2dc5f62647114b805faea1e4792"
EXPECTED_CHANNEL_SHA = (
    "550f7e645487cb2f04fb5994919452101113d6bdb3aef34fc58b2deb792d1fc2"
)
EXPECTED_ARTIFACT_ROOT = (
    "artifacts/regression_r3c/4h_short_overextension_replication_v1"
)
EXPECTED_MEMBER_IDS = (
    "btc_4h_candidate_normalized",
    "btc_4h_saturating_normalized",
    "eth_4h_tv_research_input",
)
EXPECTED_MEMBER_PATHS = {
    "btc_4h_candidate_normalized": "artifacts/trendline_family_candidate_trials/btcusdt_4h_20250801_20251201_candidate_geometry_v2/input/normalized_ohlcv.csv",
    "btc_4h_saturating_normalized": "artifacts/trendline_family_saturating_quality_trials/btcusdt_4h_20251201_20260401_saturating_quality_v1/input/normalized_ohlcv.csv",
    "eth_4h_tv_research_input": "research/model_inputs/ethusdt_4h_tv_derivatives_2025.csv",
}
EXPECTED_INPUT_MANIFEST_PATHS = {
    "btc_4h_candidate_normalized": "artifacts/trendline_family_candidate_trials/btcusdt_4h_20250801_20251201_candidate_geometry_v2/input/input_manifest.json",
    "btc_4h_saturating_normalized": "artifacts/trendline_family_saturating_quality_trials/btcusdt_4h_20251201_20260401_saturating_quality_v1/input/input_manifest.json",
}
EXPECTED_HORIZONS = (2, 4, 8, 16)
EXPECTED_REGIONS = ("LOWER_OUTER_BAND", "BELOW_OUTER")

EXPECTED_R3C1_ARTIFACTS = {
    "artifacts/regression_r3c/btcusdt_1h_momentum_context_utility_v1/study_manifest.json": "1d3a0cd3abf9c9f05ba9c416985401be5b53efd317e838e859c6373df0556752",
    "artifacts/regression_r3c/btcusdt_1h_momentum_context_utility_v1/observation_ledger.jsonl": "6d10b021efc8675dfc47b530f4f9b4e32c8e17329a8efa0b14cadefc8a4f07f6",
    "artifacts/regression_r3c/btcusdt_1h_momentum_context_utility_v1/conditional_metrics.json": "ffc1448a8e09afb8f9cdbea3a50a8df9aa6c4795c40e2267eca00e00b80af9b3",
    "artifacts/regression_r3c/btcusdt_1h_momentum_context_utility_v1/coverage_summary.json": "904c697e8e9dbe76823a094b679b176db5853952e9ec7efd954e6a1fcd388028",
    "artifacts/regression_r3c/btcusdt_1h_momentum_context_utility_v1/source_identity.json": "1072617287a5723d9418458f2b7d38942fcba8cee5934fca2e1405ec26760d0e",
    "artifacts/regression_r3c/btcusdt_1h_momentum_context_utility_v1/study_summary.md": "38d65eb6c564dd4e6978912e0525e67116cc86cf4dcbac4b847909556c9239e8",
    "artifacts/regression_r3c/btcusdt_1h_momentum_context_utility_v1/checksums.json": "083b09d466d0735009bc6523c99876073786d7ade57015bc1b646050e809c364",
}
EXPECTED_M4_FIXTURES = {
    "tests/decision/fixtures/momentum_m4/global.yaml": "a805b2efcd8d126dc9c425e6083c22939905f8bbf1136fbbb197e957c04c4ca5",
    "tests/decision/fixtures/momentum_m4/assets/BTC.yaml": "adbd011928ce80ee028cf72db5116f55dd758f7976244469defa329be7e76cdd",
    "tests/decision/fixtures/momentum_m4/assets/ETH.yaml": "a4220a9297e93ab96642e0fda6472349efeda867266a0850a326fc8adc7ca5b3",
}
EXPECTED_EVIDENCE = {
    "artifacts/decision_m3/m3_momentum_feature_semantics_certification.json": EXPECTED_M3_SHA,
    "artifacts/decision_m4/m4_momentum_decision_integration_certification.json": EXPECTED_M4_SHA,
}
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
R3C1_PREFIXES = (
    "artifacts/regression_r3c/btcusdt_1h_momentum_context_utility_v1/",
    "research/regression_r3c/btcusdt_1h_momentum_context_utility_v1.yaml",
    "scripts/analyze_regression_momentum_r3c1.py",
    "tests/scripts/test_analyze_regression_momentum_r3c1.py",
)
R3C2_PREFIXES = (
    f"{EXPECTED_ARTIFACT_ROOT}/",
    "research/regression_r3c/r3c2_4h_short_overextension_replication_v1.yaml",
    "scripts/analyze_regression_momentum_r3c2.py",
    "tests/scripts/test_analyze_regression_momentum_r3c2.py",
)


class StudyBlocked(RuntimeError):
    """Raised for an R3C2 fail-closed condition."""


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
        try:
            parsed = datetime.fromisoformat(value)
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
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


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


def _decimal(value: object, field: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise _blocked(f"{field} is not numeric") from exc
    if not parsed.is_finite():
        raise _blocked(f"{field} is not finite")
    return parsed


@dataclass(frozen=True, slots=True)
class MemberSpec:
    member_id: str
    path: Path
    provenance_class: str
    asset: str
    timeframe: str
    row_count: int
    sha256: str
    first_open_time: datetime
    last_open_time: datetime
    input_manifest_path: Path | None
    input_manifest_sha256: str | None


@dataclass(frozen=True, slots=True)
class StudyConfig:
    raw: Mapping[str, Any]
    path: Path
    members: tuple[MemberSpec, ...]
    horizons: tuple[int, ...]
    region_a: str
    region_b: str
    direction: int
    output_root: Path
    semantic_digest: str


@dataclass(frozen=True, slots=True)
class SourceData:
    spec: MemberSpec
    bars: tuple[CausalBarView, ...]
    header: tuple[str, ...]
    ignored_columns: tuple[str, ...]
    input_manifest: Mapping[str, Any] | None


@dataclass(slots=True)
class ReplayGraph:
    config: DecisionConfig
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
        retained_bars = self.bar_store.bars_at(self.key, bar.market_as_of)
        if any(item.market_as_of > bar.market_as_of for item in retained_bars):
            raise _blocked("future bar entered the Decision BarStore")
        view = self.view_builder.build_direct(
            self.lane,
            self.requirements,
            bar.market_as_of,
        )
        prepared = await self.runtime.prepare_live(
            view,
            resolver_knowledge_cutoff=bar.market_as_of,
        )
        by_id = {binding.binding_id: binding for binding in self.lane.bindings.values()}
        results_by_slot = {
            by_id[binding_id].slot_name: result
            for binding_id, result in prepared.binding_results.items()
        }
        observer_result = results_by_slot.get("observer")
        primary_result = results_by_slot.get("primary")
        if observer_result is None or primary_result is None:
            raise _blocked("R3B graph bindings are not the approved pair")
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
            "observer_decision": (
                None
                if observer_result.outcome is None
                else observer_result.outcome.decision
            ),
            "retained_count": retained,
            "market_as_of": bar.market_as_of,
        }


def _load_yaml(path: Path) -> Mapping[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise _blocked(f"cannot load study config: {exc}") from exc
    return _require_mapping(raw, "study config")


def load_study_config(path: Path = CONFIG_PATH) -> StudyConfig:
    """Load and validate the exact R3C2 research contract."""

    path = Path(path).resolve()
    root = _load_yaml(path)
    _require_exact_keys(
        root,
        {"study", "hypothesis", "members", "r3c1", "runtime", "m4_fixtures", "output"},
        "study config",
    )
    study = _require_mapping(root["study"], "study")
    _require_exact_keys(study, {"id", "version"}, "study")
    if (
        _require_text(study["id"], "study.id")
        != ("regression_r3c2_4h_short_overextension_replication_v1")
        or _require_text(study["version"], "study.version") != "1"
    ):
        raise _blocked("study identity is not the approved R3C2 identity")

    hypothesis = _require_mapping(root["hypothesis"], "hypothesis")
    _require_exact_keys(
        hypothesis,
        {"direction", "region_a", "region_b", "horizons"},
        "hypothesis",
    )
    if hypothesis["direction"] != -1 or isinstance(hypothesis["direction"], bool):
        raise _blocked("hypothesis.direction must be the fixed short direction -1")
    region_a = _require_text(hypothesis["region_a"], "hypothesis.region_a")
    region_b = _require_text(hypothesis["region_b"], "hypothesis.region_b")
    if (region_a, region_b) != EXPECTED_REGIONS:
        raise _blocked("hypothesis regions are not the approved A/B contrast")
    raw_horizons = hypothesis["horizons"]
    if (
        isinstance(raw_horizons, (str, bytes))
        or not isinstance(raw_horizons, Sequence)
        or tuple(raw_horizons) != EXPECTED_HORIZONS
    ):
        raise _blocked("hypothesis horizons must be exactly [2, 4, 8, 16]")

    raw_members = _require_mapping(root["members"], "members")
    if set(raw_members) != set(EXPECTED_MEMBER_IDS):
        raise _blocked("study members do not match the exact approved member set")
    members: list[MemberSpec] = []
    member_expectations = {
        "btc_4h_candidate_normalized": (
            "BTCUSDT",
            732,
            "canonical_normalized_artifact",
        ),
        "btc_4h_saturating_normalized": (
            "BTCUSDT",
            726,
            "canonical_normalized_artifact",
        ),
        "eth_4h_tv_research_input": ("ETHUSDT", 3124, "research_input_noncanonical"),
    }
    for member_id in EXPECTED_MEMBER_IDS:
        item = _require_mapping(raw_members[member_id], f"members.{member_id}")
        _require_exact_keys(
            item,
            {
                "path",
                "provenance_class",
                "asset",
                "timeframe",
                "row_count",
                "sha256",
                "first_open_time",
                "last_open_time",
                "input_manifest_path",
                "input_manifest_sha256",
            },
            f"members.{member_id}",
        )
        path_text = _require_text(item["path"], f"members.{member_id}.path")
        if path_text != EXPECTED_MEMBER_PATHS[member_id]:
            raise _blocked(f"members.{member_id}.path is not the frozen source path")
        source_path = (ROOT / path_text).resolve()
        if Path(path_text).is_absolute() or source_path == ROOT:
            raise _blocked(f"members.{member_id}.path must be a scoped repository path")
        asset, row_count, provenance = member_expectations[member_id]
        if (
            _require_text(
                item["provenance_class"], f"members.{member_id}.provenance_class"
            )
            != provenance
            or _require_text(item["asset"], f"members.{member_id}.asset") != asset
            or _require_text(item["timeframe"], f"members.{member_id}.timeframe")
            != "4h"
            or item["row_count"] != row_count
            or isinstance(item["row_count"], bool)
        ):
            raise _blocked(f"members.{member_id} identity is not frozen")
        first_open = _parse_utc(
            item["first_open_time"], f"members.{member_id}.first_open_time"
        )
        last_open = _parse_utc(
            item["last_open_time"], f"members.{member_id}.last_open_time"
        )
        manifest_path_value = item["input_manifest_path"]
        manifest_sha_value = item["input_manifest_sha256"]
        if member_id.startswith("btc_"):
            manifest_path_text = _require_text(
                manifest_path_value, f"members.{member_id}.input_manifest_path"
            )
            if manifest_path_text != EXPECTED_INPUT_MANIFEST_PATHS[member_id]:
                raise _blocked(f"members.{member_id}.input_manifest_path is not frozen")
            manifest_sha = _require_text(
                manifest_sha_value, f"members.{member_id}.input_manifest_sha256"
            )
            manifest_path = (ROOT / manifest_path_text).resolve()
        elif manifest_path_value is not None or manifest_sha_value is not None:
            raise _blocked("ETH must not acquire a derivative input manifest")
        else:
            manifest_path = None
            manifest_sha = None
        members.append(
            MemberSpec(
                member_id=member_id,
                path=source_path,
                provenance_class=provenance,
                asset=asset,
                timeframe="4h",
                row_count=int(item["row_count"]),
                sha256=_require_text(item["sha256"], f"members.{member_id}.sha256"),
                first_open_time=first_open,
                last_open_time=last_open,
                input_manifest_path=manifest_path,
                input_manifest_sha256=manifest_sha,
            )
        )

    r3c1 = _require_mapping(root["r3c1"], "r3c1")
    _require_exact_keys(
        r3c1,
        {
            "decision_sha256",
            "study_manifest_sha256",
            "observation_ledger_sha256",
            "conditional_metrics_sha256",
            "coverage_summary_sha256",
            "source_identity_sha256",
            "study_summary_sha256",
            "checksums_sha256",
        },
        "r3c1",
    )
    expected_r3c1 = {
        "decision_sha256": "d611018a96a2986b30d51daeec65e17db0ba326c358a18d1654bd4ff333312be",
        "study_manifest_sha256": EXPECTED_R3C1_ARTIFACTS[
            next(
                path
                for path in EXPECTED_R3C1_ARTIFACTS
                if path.endswith("study_manifest.json")
            )
        ],
        "observation_ledger_sha256": EXPECTED_R3C1_ARTIFACTS[
            next(
                path
                for path in EXPECTED_R3C1_ARTIFACTS
                if path.endswith("observation_ledger.jsonl")
            )
        ],
        "conditional_metrics_sha256": EXPECTED_R3C1_ARTIFACTS[
            next(
                path
                for path in EXPECTED_R3C1_ARTIFACTS
                if path.endswith("conditional_metrics.json")
            )
        ],
        "coverage_summary_sha256": EXPECTED_R3C1_ARTIFACTS[
            next(
                path
                for path in EXPECTED_R3C1_ARTIFACTS
                if path.endswith("coverage_summary.json")
            )
        ],
        "source_identity_sha256": EXPECTED_R3C1_ARTIFACTS[
            next(
                path
                for path in EXPECTED_R3C1_ARTIFACTS
                if path.endswith("source_identity.json")
            )
        ],
        "study_summary_sha256": EXPECTED_R3C1_ARTIFACTS[
            next(
                path
                for path in EXPECTED_R3C1_ARTIFACTS
                if path.endswith("study_summary.md")
            )
        ],
        "checksums_sha256": EXPECTED_R3C1_ARTIFACTS[
            next(
                path
                for path in EXPECTED_R3C1_ARTIFACTS
                if path.endswith("checksums.json")
            )
        ],
    }
    for key, expected in expected_r3c1.items():
        if _require_text(r3c1[key], f"r3c1.{key}") != expected:
            raise _blocked(f"R3C1 identity drifted at {key}")

    runtime = _require_mapping(root["runtime"], "runtime")
    _require_exact_keys(
        runtime,
        {
            "base_git_sha",
            "cumulative_manifest_sha256",
            "r3p_manifest_sha256",
            "m3_artifact_sha256",
            "m4_functional_artifact_sha256",
        },
        "runtime",
    )
    expected_runtime = {
        "base_git_sha": EXPECTED_BASE_SHA,
        "cumulative_manifest_sha256": EXPECTED_CUMULATIVE_MANIFEST,
        "r3p_manifest_sha256": EXPECTED_R3P_MANIFEST,
        "m3_artifact_sha256": EXPECTED_M3_SHA,
        "m4_functional_artifact_sha256": EXPECTED_M4_SHA,
    }
    for key, expected in expected_runtime.items():
        if _require_text(runtime[key], f"runtime.{key}") != expected:
            raise _blocked(f"runtime identity drifted at {key}")

    fixtures = _require_mapping(root["m4_fixtures"], "m4_fixtures")
    _require_exact_keys(
        fixtures,
        {
            "global_path",
            "global_sha256",
            "btc_path",
            "btc_sha256",
            "eth_path",
            "eth_sha256",
        },
        "m4_fixtures",
    )
    for name, expected in (
        (
            "global_sha256",
            EXPECTED_M4_FIXTURES["tests/decision/fixtures/momentum_m4/global.yaml"],
        ),
        (
            "btc_sha256",
            EXPECTED_M4_FIXTURES["tests/decision/fixtures/momentum_m4/assets/BTC.yaml"],
        ),
        (
            "eth_sha256",
            EXPECTED_M4_FIXTURES["tests/decision/fixtures/momentum_m4/assets/ETH.yaml"],
        ),
    ):
        if _require_text(fixtures[name], f"m4_fixtures.{name}") != expected:
            raise _blocked(f"M4 fixture identity drifted at {name}")
    expected_fixture_paths = {
        "global_path": "tests/decision/fixtures/momentum_m4/global.yaml",
        "btc_path": "tests/decision/fixtures/momentum_m4/assets/BTC.yaml",
        "eth_path": "tests/decision/fixtures/momentum_m4/assets/ETH.yaml",
    }
    for name, expected in expected_fixture_paths.items():
        if _require_text(fixtures[name], f"m4_fixtures.{name}") != expected:
            raise _blocked(f"M4 fixture path drifted at {name}")

    output = _require_mapping(root["output"], "output")
    _require_exact_keys(output, {"root"}, "output")
    output_text = _require_text(output["root"], "output.root")
    if output_text != EXPECTED_ARTIFACT_ROOT:
        raise _blocked("output.root is not the approved R3C2 artifact root")
    return StudyConfig(
        raw=root,
        path=path,
        members=tuple(members),
        horizons=EXPECTED_HORIZONS,
        region_a=region_a,
        region_b=region_b,
        direction=-1,
        output_root=(ROOT / output_text).resolve(),
        semantic_digest=sha256_bytes(canonical_json_bytes(root)),
    )


def _parse_source_datetime(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise _blocked(f"{field} must be a UTC datetime string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise _blocked(f"{field} has an invalid datetime") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise _blocked(f"{field} must be timezone-aware UTC")
    return parsed.astimezone(UTC)


def _validate_geometry(
    *,
    row: Mapping[str, str],
    index: int,
    opened_at: datetime,
    taker_buy_base: Decimal | None,
) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal]:
    opened = _decimal(row["open"], f"row {index}.open")
    high = _decimal(row["high"], f"row {index}.high")
    low = _decimal(row["low"], f"row {index}.low")
    close = _decimal(row["close"], f"row {index}.close")
    volume = _decimal(row["volume"], f"row {index}.volume")
    if min(opened, high, low, close) <= 0:
        raise _blocked(f"row {index} OHLC values must be positive")
    if volume < 0:
        raise _blocked(f"row {index} volume must be non-negative")
    if taker_buy_base is not None and not 0 <= taker_buy_base <= volume:
        raise _blocked(f"row {index} taker_buy_base is outside volume")
    if low > high or not low <= opened <= high or not low <= close <= high:
        raise _blocked(f"row {index} OHLC geometry is invalid")
    if opened_at.utcoffset() != timedelta(0):
        raise _blocked("source event time is not UTC")
    return opened, high, low, close, volume


def _load_input_manifest(spec: MemberSpec) -> Mapping[str, Any] | None:
    if spec.input_manifest_path is None:
        return None
    if not spec.input_manifest_path.is_file():
        raise _blocked(f"input manifest is missing: {spec.input_manifest_path}")
    actual_sha = sha256_file(spec.input_manifest_path)
    if actual_sha != spec.input_manifest_sha256:
        raise _blocked(f"input manifest SHA mismatch for {spec.member_id}")
    try:
        raw = json.loads(spec.input_manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise _blocked(f"input manifest cannot be read for {spec.member_id}") from exc
    manifest = _require_mapping(raw, f"{spec.member_id}.input_manifest")
    if manifest.get("normalized_input_sha256") != spec.sha256:
        raise _blocked(f"input manifest source SHA mismatch for {spec.member_id}")
    if manifest.get("row_count") != spec.row_count:
        raise _blocked(f"input manifest row count mismatch for {spec.member_id}")
    if (
        manifest.get("asset") != spec.asset
        or manifest.get("timeframe") != spec.timeframe
    ):
        raise _blocked(f"input manifest route mismatch for {spec.member_id}")
    return manifest


def load_source(spec: MemberSpec) -> SourceData:
    """Load only one exact local source member and validate its 4h grid."""

    if not spec.path.is_file():
        raise _blocked(f"frozen source is missing: {spec.path}")
    actual_sha = sha256_file(spec.path)
    if actual_sha != spec.sha256:
        raise _blocked(
            f"STUDY_BLOCKED_SOURCE: source SHA mismatch for {spec.member_id}"
        )
    input_manifest = _load_input_manifest(spec)
    if spec.member_id.startswith("btc_"):
        expected_header = (
            "timestamp",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "taker_buy_base",
            "complete",
        )
        ignored_columns: tuple[str, ...] = ()
    else:
        expected_header = (
            "datetime",
            "timestamp",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "open_interest",
            "funding_rate",
        )
        ignored_columns = ("timestamp", "open_interest", "funding_rate")
    try:
        with spec.path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if tuple(reader.fieldnames or ()) != expected_header:
                raise _blocked(f"source schema mismatch for {spec.member_id}")
            rows = tuple(reader)
    except (OSError, csv.Error) as exc:
        raise _blocked(f"cannot read source {spec.member_id}: {exc}") from exc
    if len(rows) != spec.row_count:
        raise _blocked(f"STUDY_BLOCKED_SOURCE: row count mismatch for {spec.member_id}")

    bars: list[CausalBarView] = []
    previous_open: datetime | None = None
    duration = timedelta(hours=4)
    for index, row in enumerate(rows):
        if set(row) != set(expected_header):
            raise _blocked(f"source row {index} schema mismatch for {spec.member_id}")
        time_field = "timestamp" if spec.member_id.startswith("btc_") else "datetime"
        opened_at = _parse_source_datetime(
            row[time_field], f"{spec.member_id}.row {index}.{time_field}"
        )
        if previous_open is not None and opened_at != previous_open + duration:
            raise _blocked(f"4h source grid defect for {spec.member_id} at row {index}")
        previous_open = opened_at
        if spec.member_id.startswith("btc_"):
            if row["complete"].strip() != "True":
                raise _blocked(f"BTC row {index} is not complete")
            taker_buy = _decimal(
                row["taker_buy_base"], f"{spec.member_id}.row {index}.taker_buy_base"
            )
        else:
            taker_buy = None
        opened, high, low, close, volume = _validate_geometry(
            row=row,
            index=index,
            opened_at=opened_at,
            taker_buy_base=taker_buy,
        )
        closed_at = opened_at + duration
        bars.append(
            CausalBarView(
                timeframe=spec.timeframe,
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
    if not bars:
        raise _blocked(f"source is empty for {spec.member_id}")
    if (
        bars[0].bar_open_at != spec.first_open_time
        or bars[-1].bar_open_at != spec.last_open_time
    ):
        raise _blocked(f"source temporal bounds mismatch for {spec.member_id}")
    return SourceData(
        spec=spec,
        bars=tuple(bars),
        header=expected_header,
        ignored_columns=ignored_columns,
        input_manifest=input_manifest,
    )


def _profile_route_identity(binding: Any) -> Mapping[str, Any]:
    certification = binding.parameters.get("certification")
    if not isinstance(certification, Mapping):
        raise _blocked("M4 Momentum binding certification is unavailable")
    return {
        "asset": certification.get("asset"),
        "decision_timeframe": certification.get("decision_timeframe"),
        "m3_artifact_sha256": certification.get("m3_artifact_sha256"),
        "route_profile_sha256": certification.get("route_profile_sha256"),
    }


def _history_value(feature_plan: Any, feature_name: str, key: MarketSeriesKey) -> int:
    history = feature_plan.history_requirements.get(feature_name)
    if not isinstance(history, Mapping) or key not in history:
        raise _blocked(f"missing {feature_name} history requirement")
    return int(history[key])


def build_replay_graph(study: StudyConfig, member: MemberSpec) -> ReplayGraph:
    """Load M4 and create exactly one in-memory R3B shadow lane."""

    for relative, expected in {**EXPECTED_M4_FIXTURES, **EXPECTED_EVIDENCE}.items():
        path = ROOT / relative
        if not path.is_file() or sha256_file(path) != expected:
            raise _blocked(
                f"STUDY_BLOCKED_RUNTIME_PARITY: protected input drifted: {relative}"
            )
    global_fixture = ROOT / "tests/decision/fixtures/momentum_m4/global.yaml"
    assets_directory = global_fixture.parent / "assets"
    ConfigManager.reset_singleton()
    manager = ConfigManager(config_dir=str(ROOT / "configs"))
    try:
        base_config = load_decision_config(
            manager,
            global_file=global_fixture,
            assets_directory=assets_directory,
        )
    finally:
        manager.shutdown()
        ConfigManager.reset_singleton()
    manifest_asset = "BTC" if member.asset == "BTCUSDT" else "ETH"
    base_asset = base_config.assets[manifest_asset]
    lane_name, base_lane = next(
        (name, lane)
        for name, lane in base_asset.lanes.items()
        if lane.decision_timeframe == "4h"
    )
    primary = base_lane.bindings.get("primary")
    if primary is None:
        raise _blocked("M4 4h lane has no primary Momentum binding")
    route_identity = _profile_route_identity(primary)
    if (
        route_identity["asset"] != member.asset
        or route_identity["decision_timeframe"] != "4h"
    ):
        raise _blocked("M4 route envelope does not match study member")
    if route_identity["m3_artifact_sha256"] != EXPECTED_M3_SHA:
        raise _blocked("M4 route does not carry the protected M3 identity")
    observer = DecisionBindingSettings(
        plugin="momentum_regression_observer",
        version="1",
        parameters={},
        dependencies={"momentum": "primary"},
    )
    updated_lane = base_lane.model_copy(
        update={
            "authority": "shadow",
            "bindings": {"primary": primary, "observer": observer},
        }
    )
    if updated_lane.bindings["primary"].parameters != primary.parameters:
        raise _blocked("in-memory R3B transformation changed Momentum parameters")
    updated_asset = base_asset.model_copy(update={"lanes": {lane_name: updated_lane}})
    base_policy = base_config.global_settings.feature_policy
    if base_policy is None:
        raise _blocked("M4 feature policy is unavailable")
    policy = FeaturePolicySettings(
        name="momentum-m4-r3c2-shadow",
        version=base_policy.version,
        allowed_features=tuple(
            sorted(set(base_policy.allowed_features) | {"REGRESSION_CONTEXT"})
        ),
    )
    global_settings = base_config.global_settings.model_copy(
        update={"feature_policy": policy}
    )
    decision_config = DecisionConfig(
        global_settings=global_settings,
        assets={manifest_asset: updated_asset},
        timeframe_grid=base_config.timeframe_grid,
        instruments=base_config.instruments,
    )
    composition = build_production_composition(decision_config)
    decision_plan = compile_decision_plan(
        composition.plugin_catalog,
        decision_config.lane_specs(),
    )
    if len(decision_plan.lanes) != 1:
        raise _blocked("transformed M4 graph must contain exactly one study lane")
    lane = decision_plan.lanes[0]
    if (
        lane.asset,
        lane.decision_timeframe,
        lane.trigger_timeframe,
        lane.authority,
    ) != (member.asset, "4h", "4h", "shadow"):
        raise _blocked("transformed M4 lane identity or authority drifted")
    if (lane.policy_name, lane.policy_version) != ("passthrough", "1"):
        raise _blocked("transformed M4 lane is not passthrough@1")
    bindings_by_slot = {
        binding.slot_name: binding for binding in lane.bindings.values()
    }
    if set(bindings_by_slot) != {"primary", "observer"}:
        raise _blocked("transformed graph binding slots drifted")
    primary_resolved = bindings_by_slot["primary"]
    observer_resolved = bindings_by_slot["observer"]
    if (primary_resolved.plugin_name, primary_resolved.plugin_version) != (
        "momentum",
        "1",
    ):
        raise _blocked("transformed graph provider is not Momentum@1")
    if (observer_resolved.plugin_name, observer_resolved.plugin_version) != (
        "momentum_regression_observer",
        "1",
    ):
        raise _blocked("transformed graph observer identity drifted")
    if observer_resolved.dependencies.get("momentum") != primary_resolved.binding_id:
        raise _blocked("observer does not resolve the real same-lane Momentum artifact")
    if lane.policy_parameters.get("source_slot") != "primary":
        raise _blocked("shadow policy source_slot is not primary")
    slot_by_id = {
        binding.binding_id: binding.slot_name for binding in lane.bindings.values()
    }
    if tuple(slot_by_id[item] for item in lane.execution_order) != (
        "primary",
        "observer",
    ):
        raise _blocked("Momentum must execute before the observer")

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
    key = requirements.decision_series
    expected_capacity = 272 if member.asset == "BTCUSDT" else 544
    expected_regression_history = 114 if member.asset == "BTCUSDT" else 181
    if len(capacities) != 1 or capacities.get(key) != expected_capacity:
        raise _blocked(
            f"compiled {member.asset}/4h capacity is not {expected_capacity}"
        )
    if (
        _history_value(feature_plan, "REGRESSION_CONTEXT", key)
        != expected_regression_history
    ):
        raise _blocked("REGRESSION_CONTEXT history is not window_size + 1")
    if _history_value(feature_plan, "MACD", key) != expected_capacity:
        raise _blocked("M4 MACD capacity does not match the approved route envelope")
    resolver = ConfigResolver.from_yaml(
        str(ROOT / "src/libs/regression/config/regression.yaml")
    )
    resolved = resolver.resolve(member.asset, "4h")
    if int(resolved.window_size) + 1 != expected_regression_history:
        raise _blocked("resolved regression window does not match the compiled history")
    if (
        channel_config_fingerprint(resolver.structural_channel_config)
        != EXPECTED_CHANNEL_SHA
    ):
        raise _blocked("structural channel identity drifted")
    feature_config_fingerprint = feature_plan.feature_config_fingerprints.get(
        "REGRESSION_CONTEXT"
    )
    if (
        not isinstance(feature_config_fingerprint, str)
        or not feature_config_fingerprint
    ):
        raise _blocked("REGRESSION_CONTEXT fingerprint is unavailable")
    bar_store = BarStore(capacities)
    runtime = ModelRuntime(
        lane,
        feature_plan,
        data_plan,
        FeatureEngine(
            composition.feature_catalog,
            bar_store,
            decision_config.timeframe_grid,
        ),
        composition.data_resolver,
        composition.runtime_plugin_catalog,
        decision_config.timeframe_grid,
    )
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
                "parameters_empty": not bool(binding.parameters),
            }
            for slot, binding in sorted(bindings_by_slot.items())
        },
        "momentum_route": route_identity,
        "observer_artifact_type": "momentum.regression_observation.v1",
        "feature_plan_fingerprint": feature_plan.feature_plan_fingerprint,
        "feature_config_fingerprint": feature_config_fingerprint,
        "regression_window_size": int(resolved.window_size),
        "regression_source_config_hash": resolved.config_hash,
        "regression_channel_config_hash": EXPECTED_CHANNEL_SHA,
        "regression_context_id": REGRESSION_CONTEXT_ID,
        "structural_estimator_id": STRUCTURAL_ESTIMATOR_ID,
        "structural_channel_id": STRUCTURAL_CHANNEL_ID,
        "compiled_history_capacity": expected_capacity,
        "feature_history_requirements": {
            name: {key.timeframe: int(next(iter(history.values())))}
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
    primary_artifact = result["primary_artifact"]
    if primary_artifact is None:
        raise _blocked("observer executed without the real Momentum artifact")
    if result["observer_decision"] is not None:
        raise _blocked("observer returned a decision")
    if artifact.artifact_type != "momentum.regression_observation.v1":
        raise _blocked("observer artifact type drifted")
    value = _thaw(artifact.value)
    provenance = _thaw(artifact.provenance)
    primary_value = _thaw(primary_artifact.value)
    if not isinstance(value, Mapping) or not isinstance(provenance, Mapping):
        raise _blocked("observer artifact shape is invalid")
    if value.get("momentum") != primary_value:
        raise _blocked("observer did not receive the real Momentum artifact")
    if provenance.get("momentum_artifact_type") != "momentum.signal.v1":
        raise _blocked("observer dependency artifact type is not momentum.signal.v1")
    if provenance.get("momentum_binding_id") != primary_artifact.binding_id:
        raise _blocked("observer provenance does not identify the primary binding")
    regression = value.get("regression")
    if not isinstance(regression, Mapping):
        raise _blocked("observer regression projection is missing")
    expected_regression_keys = {
        "slope_log_per_hour",
        "fit_quality",
        "region",
        "outer_channel_position",
        "outer_width_fraction",
        "upper_outer_breach",
        "lower_outer_breach",
        "previous_region",
        "reentered_from_upper_outer",
        "reentered_from_lower_outer",
    }
    if set(regression) != expected_regression_keys:
        raise _blocked(
            "observer regression projection is outside the approved whitelist"
        )
    return {"value": value, "provenance": provenance}


def _outcome(
    bars: Sequence[CausalBarView],
    index: int,
    horizon: int,
    direction: int,
) -> Mapping[str, Any]:
    if index + horizon >= len(bars):
        raise _blocked("outcome requested beyond the frozen source suffix")
    current = float(bars[index].close)
    future = bars[index + 1 : index + horizon + 1]
    forward = math.log(float(future[-1].close) / current)
    if direction == 0:
        aligned = favorable = adverse = continuation = None
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
    artifact: Mapping[str, Any],
    bars: Sequence[CausalBarView],
    horizons: Sequence[int],
) -> Mapping[str, Any]:
    value = artifact["value"]
    provenance = artifact["provenance"]
    momentum = value["momentum"]
    regression = value["regression"]
    direction = int(momentum["direction"])
    outcomes: dict[str, Mapping[str, Any] | None] = {}
    for horizon in horizons:
        outcomes[str(horizon)] = (
            None
            if index + horizon >= len(bars)
            else _outcome(bars, index, horizon, direction)
        )
    record = {
        "identity": {
            "member_id": None,
            "market_as_of": _iso(bar.market_as_of),
            "bar_open_at": _iso(bar.bar_open_at),
            "source_row_index": index,
        },
        "momentum": {
            "direction": direction,
            "conviction": float(momentum["conviction"]),
            "score": float(momentum["score"]),
        },
        "regression": {
            "region": regression["region"],
            "slope_log_per_hour": float(regression["slope_log_per_hour"]),
            "fit_quality": float(regression["fit_quality"]),
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
        "outcomes": outcomes,
    }
    return record


async def _replay_member(
    study: StudyConfig,
    source: SourceData,
) -> tuple[ReplayGraph, list[Mapping[str, Any]], Mapping[str, Any]]:
    graph = build_replay_graph(study, source.spec)
    records: list[Mapping[str, Any]] = []
    first_ready_index: int | None = None
    before_warmup_artifact = False
    provenance_identities: set[tuple[str, str, str, str]] = set()
    expected_capacity = int(graph.identity["compiled_history_capacity"])
    for index, bar in enumerate(source.bars):
        result = await graph.observe(bar)
        payload = _artifact_payload(result)
        if index < expected_capacity - 1:
            if payload is not None:
                before_warmup_artifact = True
            continue
        if payload is None:
            raise _blocked(
                f"STUDY_BLOCKED_RUNTIME_PARITY: no observer artifact at {source.spec.member_id} row {index}"
            )
        if first_ready_index is None:
            first_ready_index = index
        provenance = payload["provenance"]
        provenance_identities.add(
            (
                provenance["regression_source_config_hash"],
                provenance["regression_channel_config_hash"],
                provenance["regression_context_id"],
                provenance["regression_feature_config_fingerprint"],
            )
        )
        record = dict(_record(index, bar, payload, source.bars, study.horizons))
        identity = dict(record["identity"])
        identity["member_id"] = source.spec.member_id
        identity["provenance_class"] = source.spec.provenance_class
        identity["canonical_source"] = source.spec.provenance_class == (
            "canonical_normalized_artifact"
        )
        record["identity"] = identity
        records.append(record)
    if before_warmup_artifact or first_ready_index != expected_capacity - 1:
        raise _blocked(
            f"full {expected_capacity}-bar history boundary was not enforced"
        )
    if graph.history_max > expected_capacity:
        raise _blocked("Decision history exceeded the compiled member capacity")
    if not records:
        raise _blocked(f"no eligible observations for {source.spec.member_id}")
    if len(provenance_identities) != 1:
        raise _blocked("regression provenance identity changed during replay")
    return (
        graph,
        records,
        {
            "first_ready_source_row_index": first_ready_index,
            "before_warmup_observer_artifact": before_warmup_artifact,
            "all_runtime_observations_executed": True,
            "observer_decisionless": True,
            "real_momentum_dependency_observed": True,
            "history_max": graph.history_max,
            "eligible_count": len(records),
            "label_counts": {
                str(horizon): sum(
                    row["outcomes"][str(horizon)] is not None for row in records
                )
                for horizon in study.horizons
            },
        },
    )


def _metric_summary(
    rows: Sequence[Mapping[str, Any]], horizon: int
) -> Mapping[str, Any]:
    labeled = [
        row
        for row in rows
        if row["outcomes"].get(str(horizon)) is not None
        and row["outcomes"][str(horizon)]["aligned_log_return"] is not None
    ]
    aligned = [
        float(row["outcomes"][str(horizon)]["aligned_log_return"]) for row in labeled
    ]
    continuation = [
        bool(row["outcomes"][str(horizon)]["continuation"]) for row in labeled
    ]
    favorable = [
        float(row["outcomes"][str(horizon)]["favorable_excursion_log"])
        for row in labeled
    ]
    adverse = [
        float(row["outcomes"][str(horizon)]["adverse_excursion_log"]) for row in labeled
    ]
    conviction = [float(row["momentum"]["conviction"]) for row in labeled]
    return {
        "count": len(labeled),
        "mean_aligned_log_return": None
        if not aligned
        else float(statistics.fmean(aligned)),
        "median_aligned_log_return": None
        if not aligned
        else float(statistics.median(aligned)),
        "continuation_rate": None
        if not continuation
        else float(sum(continuation) / len(continuation)),
        "mean_favorable_excursion_log": None
        if not favorable
        else float(statistics.fmean(favorable)),
        "median_favorable_excursion_log": None
        if not favorable
        else float(statistics.median(favorable)),
        "mean_adverse_excursion_log": None
        if not adverse
        else float(statistics.fmean(adverse)),
        "median_adverse_excursion_log": None
        if not adverse
        else float(statistics.median(adverse)),
        "mean_momentum_conviction": None
        if not conviction
        else float(statistics.fmean(conviction)),
    }


def _subtract(left: object, right: object) -> float | None:
    if left is None or right is None:
        return None
    return float(left) - float(right)


def _contrast(
    rows: Sequence[Mapping[str, Any]],
    *,
    horizon: int,
    region_a: str,
    region_b: str,
) -> Mapping[str, Any]:
    a_rows = [row for row in rows if row["regression"]["region"] == region_a]
    b_rows = [row for row in rows if row["regression"]["region"] == region_b]
    a = _metric_summary(a_rows, horizon)
    b = _metric_summary(b_rows, horizon)
    return {
        "regions": {region_a: a, region_b: b},
        "return_spread_h": _subtract(
            a["mean_aligned_log_return"], b["mean_aligned_log_return"]
        ),
        "continuation_spread_h": _subtract(
            a["continuation_rate"], b["continuation_rate"]
        ),
        "MFE_spread_h": _subtract(
            a["mean_favorable_excursion_log"], b["mean_favorable_excursion_log"]
        ),
        "MAE_spread_h": _subtract(
            a["mean_adverse_excursion_log"], b["mean_adverse_excursion_log"]
        ),
        "adverse_excursion_spread_interpretation": (
            "A_minus_B; negative means LOWER_OUTER_BAND has lower mean adverse excursion"
        ),
    }


def _monthly(
    records: Sequence[Mapping[str, Any]],
    study: StudyConfig,
) -> Mapping[str, Any]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in records:
        grouped[row["identity"]["bar_open_at"][:7]].append(row)
    result: dict[str, Any] = {}
    for month, rows in sorted(grouped.items()):
        result[month] = {
            "eligible_count": len(rows),
            "direction_counts": {
                "long": sum(row["momentum"]["direction"] == 1 for row in rows),
                "short": sum(row["momentum"]["direction"] == -1 for row in rows),
                "neutral": sum(row["momentum"]["direction"] == 0 for row in rows),
            },
            "short": {
                str(horizon): _monthly_contrast(
                    [row for row in rows if row["momentum"]["direction"] == -1],
                    horizon,
                    study,
                )
                for horizon in study.horizons
            },
            "long_negative_control": {
                str(horizon): _monthly_contrast(
                    [row for row in rows if row["momentum"]["direction"] == 1],
                    horizon,
                    study,
                )
                for horizon in study.horizons
            },
        }
    return result


def _monthly_contrast(
    rows: Sequence[Mapping[str, Any]],
    horizon: int,
    study: StudyConfig,
) -> Mapping[str, Any]:
    a_rows = [
        row
        for row in rows
        if row["regression"]["region"] == study.region_a
        and row["outcomes"].get(str(horizon)) is not None
    ]
    b_rows = [
        row
        for row in rows
        if row["regression"]["region"] == study.region_b
        and row["outcomes"].get(str(horizon)) is not None
    ]
    a = _metric_summary(a_rows, horizon)
    b = _metric_summary(b_rows, horizon)
    return {
        "region_a_count": a["count"],
        "region_b_count": b["count"],
        "return_spread_h": _subtract(
            a["mean_aligned_log_return"], b["mean_aligned_log_return"]
        )
        if a["count"] and b["count"]
        else None,
    }


def _member_metrics(
    records: Sequence[Mapping[str, Any]],
    study: StudyConfig,
) -> Mapping[str, Any]:
    short_rows = [row for row in records if row["momentum"]["direction"] == -1]
    long_rows = [row for row in records if row["momentum"]["direction"] == 1]
    primary = {
        str(horizon): {
            "baseline": _metric_summary(short_rows, horizon),
            **_contrast(
                short_rows,
                horizon=horizon,
                region_a=study.region_a,
                region_b=study.region_b,
            ),
        }
        for horizon in study.horizons
    }
    long_control = {
        str(horizon): {
            "baseline": _metric_summary(long_rows, horizon),
            **_contrast(
                long_rows,
                horizon=horizon,
                region_a=study.region_a,
                region_b=study.region_b,
            ),
        }
        for horizon in study.horizons
    }
    return {
        "eligible_count": len(records),
        "direction_counts": {
            "long": len(long_rows),
            "short": len(short_rows),
            "neutral": sum(row["momentum"]["direction"] == 0 for row in records),
        },
        "short_region_counts": {
            study.region_a: sum(
                row["regression"]["region"] == study.region_a for row in short_rows
            ),
            study.region_b: sum(
                row["regression"]["region"] == study.region_b for row in short_rows
            ),
        },
        "primary_short_contrast": primary,
        "long_negative_control": long_control,
        "monthly": _monthly(records, study),
    }


def _sign(value: object) -> str:
    if value is None:
        return "undefined"
    if float(value) > 0:
        return "positive"
    if float(value) < 0:
        return "negative"
    return "zero"


async def _causality_probe(
    study: StudyConfig,
    source: SourceData,
    records: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any]:
    candidates = [
        row
        for row in records
        if row["momentum"]["direction"] != 0 and row["outcomes"].get("4") is not None
    ]
    if not candidates:
        raise _blocked(
            f"no non-neutral causality probe exists for {source.spec.member_id}"
        )
    probe = candidates[0]
    probe_index = int(probe["identity"]["source_row_index"])
    direction = int(probe["momentum"]["direction"])
    original_graph = build_replay_graph(study, source.spec)
    original_payload: Mapping[str, Any] | None = None
    for bar in source.bars[: probe_index + 1]:
        original_payload = _artifact_payload(await original_graph.observe(bar))
    if original_payload is None:
        raise _blocked("causality probe did not reach an eligible observation")
    mutated_bars = list(source.bars)
    for index in range(probe_index + 1, len(mutated_bars)):
        bar = mutated_bars[index]
        close = bar.close * Decimal("1.01")
        mutated_bars[index] = replace(
            bar,
            high=max(bar.high, bar.open, close),
            low=min(bar.low, bar.open, close),
            close=close,
        )
    mutated_graph = build_replay_graph(study, source.spec)
    mutated_payload: Mapping[str, Any] | None = None
    for bar in source.bars[: probe_index + 1]:
        mutated_payload = _artifact_payload(await mutated_graph.observe(bar))
    if mutated_payload is None:
        raise _blocked("mutated causality probe did not reach an eligible observation")
    observation_bytes = canonical_json_bytes(original_payload)
    mutated_observation_bytes = canonical_json_bytes(mutated_payload)
    original_label = _outcome(source.bars, probe_index, 4, direction)
    mutated_label = _outcome(tuple(mutated_bars), probe_index, 4, direction)
    return {
        "member_id": source.spec.member_id,
        "probe_source_row_index": probe_index,
        "probe_direction": direction,
        "probe_horizon": 4,
        "observation_byte_identical": observation_bytes == mutated_observation_bytes,
        "original_observation_sha256": sha256_bytes(observation_bytes),
        "mutated_observation_sha256": sha256_bytes(mutated_observation_bytes),
        "future_label_changed": original_label != mutated_label,
        "original_label": original_label,
        "mutated_label": mutated_label,
        "future_suffix_supplied_before_cutoff": False,
        "original_history_max": original_graph.history_max,
        "mutated_history_max": mutated_graph.history_max,
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
                {"path": relative, "state": "file", "sha256": sha256_file(path)}
            )
        else:
            records.append({"path": relative, "state": "deleted"})
    ordered = tuple(sorted(records, key=lambda item: str(item["path"])))
    return ordered, sha256_bytes(canonical_json_bytes(ordered))


def _preserved_manifests(root: Path) -> Mapping[str, Any]:
    excluded = (*R3C1_PREFIXES, *R3C2_PREFIXES)
    cumulative_records, cumulative_hash = canonical_worktree_manifest(
        root, excluded_prefixes=excluded
    )
    r3p_records, r3p_hash = canonical_worktree_manifest(
        root, excluded_prefixes=(*excluded, *R3B_ONLY_PATHS)
    )
    if (len(cumulative_records), cumulative_hash) != (84, EXPECTED_CUMULATIVE_MANIFEST):
        raise _blocked(
            f"pre-R3C2 cumulative manifest drifted: records={len(cumulative_records)} sha256={cumulative_hash}"
        )
    if (len(r3p_records), r3p_hash) != (77, EXPECTED_R3P_MANIFEST):
        raise _blocked(
            f"R3P manifest drifted: records={len(r3p_records)} sha256={r3p_hash}"
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


def _verify_fixed_files() -> None:
    for relative, expected in {
        **EXPECTED_M4_FIXTURES,
        **EXPECTED_EVIDENCE,
        **EXPECTED_R3C1_ARTIFACTS,
    }.items():
        path = ROOT / relative
        if not path.is_file() or sha256_file(path) != expected:
            raise _blocked(f"immutable protected file drifted: {relative}")


def _json_write(path: Path, value: object) -> None:
    path.write_bytes(canonical_json_bytes(value) + b"\n")


def _artifact_paths(output: Path) -> tuple[Path, ...]:
    return (
        output / "study_manifest.json",
        output / "source_audit.json",
        output / "coverage_summary.json",
        output / "replication_metrics.json",
        output / "member_observations" / "btc_4h_candidate.jsonl",
        output / "member_observations" / "btc_4h_saturating.jsonl",
        output / "member_observations" / "eth_4h_research.jsonl",
        output / "study_summary.md",
        output / "checksums.json",
    )


def _verify_artifacts(output: Path) -> Mapping[str, Any]:
    expected_paths = _artifact_paths(output)
    expected_relative = {path.relative_to(output).as_posix() for path in expected_paths}
    actual_relative = {
        path.relative_to(output).as_posix()
        for path in output.rglob("*")
        if path.is_file()
    }
    if actual_relative != expected_relative:
        raise _blocked(
            f"artifact inventory mismatch; missing={sorted(expected_relative - actual_relative)}, "
            f"unexpected={sorted(actual_relative - expected_relative)}"
        )
    checksums = json.loads((output / "checksums.json").read_text(encoding="utf-8"))
    if checksums.get("algorithm") != "sha256":
        raise _blocked("artifact checksum algorithm drifted")
    files = checksums.get("files")
    expected_checksum_keys = expected_relative - {"checksums.json"}
    if not isinstance(files, Mapping) or set(files) != expected_checksum_keys:
        raise _blocked("artifact checksum inventory drifted")
    for relative in sorted(expected_checksum_keys):
        if sha256_file(output / relative) != files[relative]:
            raise _blocked(f"artifact checksum mismatch: {relative}")
    return {"verified": True, "covered_files": len(files)}


def _write_artifacts(
    study: StudyConfig,
    sources: Mapping[str, SourceData],
    graphs: Mapping[str, ReplayGraph],
    records_by_member: Mapping[str, Sequence[Mapping[str, Any]]],
    replay_checks: Mapping[str, Mapping[str, Any]],
    causality: Mapping[str, Mapping[str, Any]],
    preserved: Mapping[str, Any],
) -> Mapping[str, Any]:
    output = study.output_root
    output.mkdir(parents=True, exist_ok=True)
    observations_dir = output / "member_observations"
    observations_dir.mkdir(parents=True, exist_ok=True)
    metrics_by_member = {
        member_id: {
            "provenance_class": sources[member_id].spec.provenance_class,
            "canonical_source": sources[member_id].spec.provenance_class
            == "canonical_normalized_artifact",
            **_member_metrics(records_by_member[member_id], study),
        }
        for member_id in EXPECTED_MEMBER_IDS
    }
    return_spread_matrix = {
        member_id: {
            str(horizon): metrics_by_member[member_id]["primary_short_contrast"][
                str(horizon)
            ]["return_spread_h"]
            for horizon in study.horizons
        }
        for member_id in EXPECTED_MEMBER_IDS
    }
    continuation_spread_matrix = {
        member_id: {
            str(horizon): metrics_by_member[member_id]["primary_short_contrast"][
                str(horizon)
            ]["continuation_spread_h"]
            for horizon in study.horizons
        }
        for member_id in EXPECTED_MEMBER_IDS
    }
    sign_matrix = {
        member_id: {
            str(horizon): _sign(return_spread_matrix[member_id][str(horizon)])
            for horizon in study.horizons
        }
        for member_id in EXPECTED_MEMBER_IDS
    }
    replication_metrics = {
        "status": "STUDY_COMPLETE",
        "hypothesis": {
            "direction": study.direction,
            "region_a": study.region_a,
            "region_b": study.region_b,
            "primary_horizons": list(study.horizons),
            "expected_return_spread_sign": "positive",
            "no_minimum_spread_magnitude": True,
        },
        "adverse_excursion_spread_interpretation": (
            "MAE_spread_h is A_minus_B; negative means A has lower mean adverse excursion"
        ),
        "members": metrics_by_member,
        "return_spread_matrix": return_spread_matrix,
        "continuation_spread_matrix": continuation_spread_matrix,
        "return_spread_sign_matrix": sign_matrix,
        "no_alternative_search_performed": True,
        "no_iid_significance_reported": True,
    }
    source_audit = {
        "status": "STUDY_COMPLETE",
        "members": {
            member_id: {
                "path": str(source.spec.path.relative_to(ROOT)),
                "provenance_class": source.spec.provenance_class,
                "asset": source.spec.asset,
                "timeframe": source.spec.timeframe,
                "sha256": source.spec.sha256,
                "row_count": len(source.bars),
                "header": list(source.header),
                "first_open_time": _iso(source.bars[0].bar_open_at),
                "last_open_time": _iso(source.bars[-1].bar_open_at),
                "source_end": _iso(source.bars[-1].bar_close_at),
                "contiguous_four_hour_grid": True,
                "duplicate_timestamps": False,
                "finite_positive_ohlc": True,
                "finite_non_negative_volume": True,
                "complete_bars_only": member_id.startswith("btc_"),
                "taker_buy_base_used": member_id.startswith("btc_"),
                "ignored_columns": list(source.ignored_columns),
                "derivative_columns_used": [],
                "input_manifest_path": (
                    None
                    if source.spec.input_manifest_path is None
                    else str(source.spec.input_manifest_path.relative_to(ROOT))
                ),
                "input_manifest_sha256": source.spec.input_manifest_sha256,
                "eth_noncanonical_label": source.spec.provenance_class
                == "research_input_noncanonical",
            }
            for member_id, source in sources.items()
        },
        "provider_or_network_fallback": False,
    }
    coverage = {
        "status": "STUDY_COMPLETE",
        "members": {
            member_id: {
                "provenance_class": sources[member_id].spec.provenance_class,
                "eligible_observation_count": len(records_by_member[member_id]),
                "direction_counts": metrics_by_member[member_id]["direction_counts"],
                "short_region_counts": metrics_by_member[member_id][
                    "short_region_counts"
                ],
                "first_ready_source_row_index": replay_checks[member_id][
                    "first_ready_source_row_index"
                ],
                "history_max": replay_checks[member_id]["history_max"],
                "history_capacity_bound": graphs[member_id].identity[
                    "compiled_history_capacity"
                ],
                "all_eligible_momentum_outputs_recorded": True,
                "outcomes_attached_after_observation": True,
                "labeled_counts_by_horizon": replay_checks[member_id]["label_counts"],
            }
            for member_id in EXPECTED_MEMBER_IDS
        },
        "causality": causality,
        "publication_called": False,
        "fusion_or_promotion_status_emitted": False,
        "preserved_manifests": preserved,
        "r3c1_artifacts_byte_identical": True,
        "study_config_digest": study.semantic_digest,
    }
    for member_id in EXPECTED_MEMBER_IDS:
        path = (
            observations_dir
            / {
                "btc_4h_candidate_normalized": "btc_4h_candidate.jsonl",
                "btc_4h_saturating_normalized": "btc_4h_saturating.jsonl",
                "eth_4h_tv_research_input": "eth_4h_research.jsonl",
            }[member_id]
        )
        path.write_bytes(
            b"".join(
                canonical_json_bytes(row) + b"\n"
                for row in records_by_member[member_id]
            )
        )
    _json_write(output / "source_audit.json", source_audit)
    _json_write(output / "coverage_summary.json", coverage)
    _json_write(output / "replication_metrics.json", replication_metrics)
    summary_lines = [
        "# R3C2 4h Short-Momentum Overextension Replication",
        "",
        "Status: `STUDY_COMPLETE`",
        "",
        "This deterministic PIT-safe study evaluates only the predeclared short-Momentum",
        "LOWER_OUTER_BAND versus BELOW_OUTER contrast. It does not search alternatives,",
        "define a fusion rule, or recommend promotion.",
        "",
        f"- Primary horizons: `{list(study.horizons)}` 4h bars",
        f"- Region A: `{study.region_a}`",
        f"- Region B: `{study.region_b}`",
        "",
        "## Return-spread sign matrix",
        "",
        "| member | h2 | h4 | h8 | h16 | provenance |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for member_id in EXPECTED_MEMBER_IDS:
        values = sign_matrix[member_id]
        summary_lines.append(
            f"| {member_id} | {values['2']} | {values['4']} | {values['8']} | {values['16']} | {sources[member_id].spec.provenance_class} |"
        )
    summary_lines.extend(
        [
            "",
            "No automatic approval or promotion disposition is emitted.",
            "",
        ]
    )
    (output / "study_summary.md").write_text("\n".join(summary_lines), encoding="utf-8")

    non_self_paths = [
        path.relative_to(output).as_posix()
        for path in _artifact_paths(output)
        if path.name not in {"checksums.json", "study_manifest.json"}
    ]
    artifact_hashes = {
        relative: sha256_file(output / relative) for relative in sorted(non_self_paths)
    }
    study_manifest = {
        "status": "STUDY_COMPLETE",
        "study_identity": {
            "study_id": study.raw["study"]["id"],
            "study_version": study.raw["study"]["version"],
            "base_git_sha": EXPECTED_BASE_SHA,
            "cumulative_manifest_sha256": EXPECTED_CUMULATIVE_MANIFEST,
            "r3p_manifest_sha256": EXPECTED_R3P_MANIFEST,
            "r3c1_decision_sha256": study.raw["r3c1"]["decision_sha256"],
            "r3c1_artifact_hashes": {
                key: value for key, value in study.raw["r3c1"].items()
            },
            "m3_artifact_sha256": EXPECTED_M3_SHA,
            "m4_functional_artifact_sha256": EXPECTED_M4_SHA,
            "m4_fixture_identity": dict(study.raw["m4_fixtures"]),
            "study_config_digest": study.semantic_digest,
            "hypothesis": {
                "direction": study.direction,
                "region_a": study.region_a,
                "region_b": study.region_b,
                "horizons": list(study.horizons),
            },
        },
        "members": {
            member_id: {
                "path": str(sources[member_id].spec.path.relative_to(ROOT)),
                "asset": sources[member_id].spec.asset,
                "timeframe": "4h",
                "provenance_class": sources[member_id].spec.provenance_class,
                "canonical_source": sources[member_id].spec.provenance_class
                == "canonical_normalized_artifact",
                "sha256": sources[member_id].spec.sha256,
                "row_count": len(sources[member_id].bars),
                "input_manifest_path": (
                    None
                    if sources[member_id].spec.input_manifest_path is None
                    else str(
                        sources[member_id].spec.input_manifest_path.relative_to(ROOT)
                    )
                ),
                "input_manifest_sha256": sources[member_id].spec.input_manifest_sha256,
                "route_identity": graphs[member_id].identity,
            }
            for member_id in EXPECTED_MEMBER_IDS
        },
        "replication_metrics": {
            "return_spread_matrix": return_spread_matrix,
            "continuation_spread_matrix": continuation_spread_matrix,
            "return_spread_sign_matrix": sign_matrix,
        },
        "causality": causality,
        "artifact_inventory": [
            {"path": relative, "state": "file", "sha256": artifact_hashes[relative]}
            for relative in sorted(artifact_hashes)
        ],
        "manifest_hashing_note": (
            "The manifest records every non-self research artifact except checksums.json; "
            "checksums.json covers the manifest and all other artifacts without a circular digest."
        ),
    }
    _json_write(output / "study_manifest.json", study_manifest)
    checksum_files = {
        path.relative_to(output).as_posix(): sha256_file(path)
        for path in _artifact_paths(output)
        if path.name != "checksums.json"
    }
    _json_write(
        output / "checksums.json", {"algorithm": "sha256", "files": checksum_files}
    )
    verified = _verify_artifacts(output)
    return {
        "output_root": str(output.relative_to(ROOT)),
        "artifact_hashes": {
            path.relative_to(output).as_posix(): sha256_file(path)
            for path in _artifact_paths(output)
        },
        "artifact_verification": verified,
        "return_spread_matrix": return_spread_matrix,
        "continuation_spread_matrix": continuation_spread_matrix,
        "return_spread_sign_matrix": sign_matrix,
    }


async def _run_research(
    study: StudyConfig,
) -> tuple[
    Mapping[str, SourceData],
    Mapping[str, ReplayGraph],
    Mapping[str, Sequence[Mapping[str, Any]]],
    Mapping[str, Mapping[str, Any]],
    Mapping[str, Mapping[str, Any]],
]:
    sources = {member.member_id: load_source(member) for member in study.members}
    graphs: dict[str, ReplayGraph] = {}
    records_by_member: dict[str, Sequence[Mapping[str, Any]]] = {}
    replay_checks: dict[str, Mapping[str, Any]] = {}
    causality: dict[str, Mapping[str, Any]] = {}
    for member_id in EXPECTED_MEMBER_IDS:
        graph, records, checks = await _replay_member(study, sources[member_id])
        graphs[member_id] = graph
        records_by_member[member_id] = records
        replay_checks[member_id] = checks
        causality[member_id] = await _causality_probe(
            study,
            sources[member_id],
            records,
        )
        if not causality[member_id]["observation_byte_identical"]:
            raise _blocked(f"causality observation changed for {member_id}")
        if not causality[member_id]["future_label_changed"]:
            raise _blocked(f"causality future label did not change for {member_id}")
    return sources, graphs, records_by_member, replay_checks, causality


def run_study(study: StudyConfig | None = None) -> Mapping[str, Any]:
    study = study or load_study_config()
    base_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if base_sha != EXPECTED_BASE_SHA:
        raise _blocked("study worktree base SHA is not the approved current-main base")
    _verify_fixed_files()
    preserved_before = _preserved_manifests(ROOT)
    sources, graphs, records_by_member, replay_checks, causality = asyncio.run(
        _run_research(study)
    )
    preserved_after_replay = _preserved_manifests(ROOT)
    if preserved_after_replay != preserved_before:
        raise _blocked("runtime manifest changed during the research replay")
    artifact_result = _write_artifacts(
        study,
        sources,
        graphs,
        records_by_member,
        replay_checks,
        causality,
        preserved_before,
    )
    preserved_after_write = _preserved_manifests(ROOT)
    if preserved_after_write != preserved_before:
        raise _blocked("runtime manifest changed while writing research artifacts")
    return {
        "status": "STUDY_COMPLETE",
        "study_id": study.raw["study"]["id"],
        "study_config_digest": study.semantic_digest,
        "members": {
            member_id: {
                "path": str(sources[member_id].spec.path.relative_to(ROOT)),
                "asset": sources[member_id].spec.asset,
                "timeframe": "4h",
                "provenance_class": sources[member_id].spec.provenance_class,
                "sha256": sources[member_id].spec.sha256,
                "rows": len(sources[member_id].bars),
                "eligible_observations": len(records_by_member[member_id]),
                "direction_counts": _member_metrics(
                    records_by_member[member_id], study
                )["direction_counts"],
                "route": graphs[member_id].identity,
                "replay": replay_checks[member_id],
                "causality": causality[member_id],
            }
            for member_id in EXPECTED_MEMBER_IDS
        },
        "artifact_result": artifact_result,
        "preserved_manifests": preserved_after_write,
        "no_network_provider_calls": True,
        "no_alternative_search": True,
        "no_promotion_disposition": True,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    args = parser.parse_args(argv)
    try:
        result = run_study(load_study_config(args.config))
    except StudyBlocked as exc:
        print(
            f"REGRESSION_R3C2_4H_SHORT_OVEREXTENSION_REPLICATION_BLOCKED: {exc}",
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    print("REGRESSION_R3C2_4H_SHORT_OVEREXTENSION_REPLICATION_COMPLETE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
