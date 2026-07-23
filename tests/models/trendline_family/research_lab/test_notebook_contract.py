from __future__ import annotations

import ast
import asyncio
import inspect
import json
from pathlib import Path

import pandas as pd

from libs.models.trendline_family import MTFNormalizationContext
from libs.models.trendline_family.config import ResolvedTrendlineFamilyConfig, TrendlineFamilyConfig
from libs.models.trendline_family.config_resolver import TrendlineFamilyConfigResolver
from libs.models.trendline_family.research_lab import (
    build_smoke_config,
    build_smoke_ohlcv,
    immutable_research_frame,
    run_canonical_replay,
)


NOTEBOOK = Path("research/trendline_family_research_lab.ipynb")


def _non_smoke_config(*, asset: str = "BTCUSDT", timeframe: str = "1h") -> ResolvedTrendlineFamilyConfig:
    smoke = build_smoke_config(asset=asset, timeframe=timeframe)
    return ResolvedTrendlineFamilyConfig.create(
        asset=asset,
        timeframe=timeframe,
        config_version="research_test_v1",
        config=TrendlineFamilyConfig(candidate=smoke.candidate),
        field_provenance={"research_test": "explicit_non_smoke"},
    )


def _mtf_fixture():
    dataset = immutable_research_frame(
        frame=build_smoke_ohlcv(),
        asset="BTCUSDT",
        timeframe="1h",
    )
    replay = run_canonical_replay(dataset=dataset, config=build_smoke_config())
    selected = replay.outputs[-1].snapshot
    config = TrendlineFamilyConfigResolver(
        {
            "version": "research-mtf-notebook-v1",
            "defaults": {
                "mtf": {
                    "enabled": True,
                    "source_timeframes": ["1h", "4h"],
                    "minimum_confluence_timeframes": 2,
                    "max_source_age_bars": 4.0,
                    "stale_include_age_bars": 1.0,
                    "max_level_distance_atr": 1.0,
                    "max_corridor_separation_atr": 1.0,
                    "max_slope_delta_atr_per_hour": 1.0,
                    "intersection_horizon_bars": 24,
                    "normalization_policy": "decision_timeframe_atr",
                }
            },
        }
    ).resolve(asset="BTCUSDT", timeframe="1h")
    normalization = MTFNormalizationContext(
        asset="BTCUSDT",
        decision_timeframe="1h",
        atr=2.0,
        decision_price=float(dataset.to_frame().iloc[-1]["close"]),
    )
    return config, {"1h": selected}, normalization


def _notebook_text() -> str:
    payload = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    return "\n".join("".join(cell.get("source", ())) for cell in payload["cells"])


def _execute_notebook(
    *,
    replacements: dict[str, str] | None = None,
    namespace: dict[str, object] | None = None,
) -> dict[str, object]:
    payload = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    namespace = {"__name__": "__research_notebook_test__", "display": lambda *_args, **_kwargs: None, **(namespace or {})}
    for position, cell in enumerate(payload["cells"]):
        if cell.get("cell_type") != "code":
            continue
        source = "".join(cell["source"])
        for before, after in (replacements or {}).items():
            source = source.replace(before, after)
        code = compile(source, f"<research notebook cell {position}>", "exec", flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)
        result = eval(code, namespace)
        if inspect.iscoroutine(result):
            asyncio.run(result)
    return namespace


def test_notebook_is_clean_nbformat_v4_with_required_sections() -> None:
    payload = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    assert payload["nbformat"] == 4
    assert isinstance(payload["cells"], list)
    assert payload["cells"]
    assert all(cell.get("outputs", []) == [] for cell in payload["cells"] if cell["cell_type"] == "code")
    text = _notebook_text()
    for heading in (
        "# Trendline Family Research Lab",
        "## 0. Scope, Safety, and Execution Mode",
        "## 3. Canonical Single-Timeframe Replay",
        "## 8. Point-in-Time Replay Evidence",
        "## 10. Multi-Timeframe Geometry Evidence",
        "## 11. Phase-I Artifact Browser",
        "## 15. Export and Reproducibility",
    ):
        assert heading in text


def test_notebook_defaults_stay_offline_and_exclude_forbidden_work() -> None:
    text = _notebook_text()
    for flag in (
        "SMOKE_MODE = True",
        "FETCH_REMOTE = False",
        "RUN_POINT_IN_TIME_REPLAY = False",
        "RUN_MTF_RESEARCH = False",
        "RUN_MULTI_ASSET_COMPARISON = False",
        "EXPORT_ARTIFACTS = False",
    ):
        assert flag in text
    assert "libs.models.regime_v2" not in text
    assert "libs.trendlines" not in text
    assert "trendlines_old" not in text
    assert "/Users/" not in text
    assert "API_KEY" not in text
    assert "SECRET" not in text
    assert "render_replay_step" in text
    assert "verify_artifact_bundle" not in text  # Support loader owns verification.
    for retired_visualization in (
        "plot" + "ly",
        "build_" + "price_figure",
        "build_" + "mtf_projection_figure",
        "build_" + "validation_sensitivity_figure",
        "figure" + ".show(",
        "." + "show()",
    ):
        assert retired_visualization not in text
    for dead_control in (
        "RUN_PHASE_I_EXPERIMENT",
        "SOURCE_TIMEFRAMES",
        "FOLD_PARAMETERS",
        "REPLAY_START_POSITION",
        "CANDIDATE_OUTCOME_POLICY",
        "INTERACTION_OUTCOME_POLICY",
    ):
        assert dead_control not in text


def test_active_trendline_research_paths_have_no_legacy_visualization_launches() -> None:
    roots = (
        Path("src/libs/models/trendline/research_lab"),
        Path("src/libs/models/trendline_family/research_lab"),
        Path("research/trendline_family_research_lab.ipynb"),
        Path("tests/models/trendline_family/research_lab"),
    )
    paths = tuple(
        path for root in roots
        for path in ((root,) if root.is_file() else root.glob("*.py"))
    )
    forbidden = (
        "import " + "plotly",
        "from " + "plotly",
        "plot" + "ly.graph_objects",
        "figure" + ".show(",
        "webbrowser" + ".open",
        "Play" + "wright",
        "Selen" + "ium",
        "Puppe" + "teer",
    )
    offenders = [
        path for path in paths
        if any(token in path.read_text(encoding="utf-8") for token in forbidden)
    ]
    assert offenders == []


def test_default_notebook_cells_execute_and_event_transition_adapter_is_available() -> None:
    namespace = _execute_notebook()
    assert callable(namespace["event_transition_rows"])
    assert namespace["replay"].context.research_run_id


def test_notebook_local_replay_and_export_modes_are_independently_reachable(tmp_path: Path) -> None:
    fixture = tmp_path / "ohlcv.csv"
    index = pd.date_range("2024-01-01", periods=24, freq="h", tz="UTC")
    pd.DataFrame(
        {
            "timestamp": index.astype(str), "open": 100.0, "high": 101.0, "low": 99.0,
            "close": 100.0, "volume": 1.0, "complete": True,
        }
    ).to_csv(fixture, index=False)
    namespace = _execute_notebook(
        replacements={
            "SMOKE_MODE = True": "SMOKE_MODE = False",
            "RUN_POINT_IN_TIME_REPLAY = False": "RUN_POINT_IN_TIME_REPLAY = True",
                "EXPORT_ARTIFACTS = False": "EXPORT_ARTIFACTS = True",
                "LOCAL_DATA_PATH = None": f"LOCAL_DATA_PATH = {str(fixture)!r}",
                "RESOLVED_CONFIG = None": "RESOLVED_CONFIG = NON_SMOKE_CONFIG",
            "OUTPUT_ROOT = PROJECT_ROOT / 'artifacts' / 'trendline_family_research_lab'": f"OUTPUT_ROOT = {str(tmp_path / 'exports')!r}",
        },
        namespace={"NON_SMOKE_CONFIG": _non_smoke_config()},
    )
    assert namespace["dataset"].row_count == 24
    assert namespace["exported"]


def test_notebook_remote_mode_uses_aware_utc_millisecond_bounds_and_adapter_timestamp_column() -> None:
    remote = pd.DataFrame(
        {
            "timestamp": [1_704_067_200_000, 1_704_070_800_000],
            "open": [100.0, 101.0], "high": [101.0, 102.0], "low": [99.0, 100.0],
            "close": [100.5, 101.5], "volume": [1.0, 1.0],
        }
    )
    adapter = (
        "class BinanceNativeAdapter:\n"
        "        async def get_historical_ohlcv(self, symbol, timeframe, since, until):\n"
        "            assert (symbol, timeframe, since, until) == ('BTCUSDT', '1h', 1704067200000, 1704078000000)\n"
        "            return REMOTE_FRAME.copy()"
    )
    namespace = _execute_notebook(
        replacements={
            "SMOKE_MODE = True": "SMOKE_MODE = False",
            "FETCH_REMOTE = False": "FETCH_REMOTE = True",
            "START = None": "START = '2024-01-01T00:00:00Z'",
            "END = None": "END = '2024-01-01T03:00:00Z'",
            "RESOLVED_CONFIG = None": "RESOLVED_CONFIG = NON_SMOKE_CONFIG",
            "from apps.ingestion_app.adapters.binance_native import BinanceNativeAdapter": adapter,
        },
        namespace={"REMOTE_FRAME": remote, "NON_SMOKE_CONFIG": _non_smoke_config()},
    )
    assert tuple(namespace["dataset"].timestamps) == (
        pd.Timestamp("2024-01-01T00:00:00Z").to_pydatetime(),
        pd.Timestamp("2024-01-01T01:00:00Z").to_pydatetime(),
    )


def test_notebook_mtf_and_export_bind_separate_policy_identity(tmp_path: Path) -> None:
    mtf_config, source_snapshots, normalization = _mtf_fixture()
    namespace = _execute_notebook(
        replacements={
            "RUN_MTF_RESEARCH = False": "RUN_MTF_RESEARCH = True",
            "EXPORT_ARTIFACTS = False": "EXPORT_ARTIFACTS = True",
            "MTF_RESOLVED_CONFIG = None": "MTF_RESOLVED_CONFIG = MTF_CONFIG_INPUT",
            "MTF_SOURCE_SNAPSHOTS = None": "MTF_SOURCE_SNAPSHOTS = MTF_SOURCE_INPUT",
            "MTF_NORMALIZATION_CONTEXT = None": "MTF_NORMALIZATION_CONTEXT = MTF_NORMALIZATION_INPUT",
            "OUTPUT_ROOT = PROJECT_ROOT / 'artifacts' / 'trendline_family_research_lab'": f"OUTPUT_ROOT = {str(tmp_path / 'exports')!r}",
        },
        namespace={
            "MTF_CONFIG_INPUT": mtf_config,
            "MTF_SOURCE_INPUT": source_snapshots,
            "MTF_NORMALIZATION_INPUT": normalization,
        },
    )
    assert namespace["mtf_snapshot"].policy_audit.mtf_config_hash == mtf_config.mtf_config_hash
    assert namespace["exported"]["mtf_snapshot"].is_file()
    manifest = json.loads(namespace["exported"]["export_manifest"].read_text(encoding="utf-8"))
    assert manifest["replay_config_version"] == "research_smoke_v1"
    assert manifest["replay_mtf_config_hash"] == namespace["replay"].context.mtf_config_hash
    assert manifest["mtf_config_version"] == "research-mtf-notebook-v1"
    assert manifest["mtf_config_hash"] == mtf_config.mtf_config_hash


def test_notebook_point_in_time_position_zero_renders_first_snapshot() -> None:
    namespace = _execute_notebook(
        replacements={
            "RUN_POINT_IN_TIME_REPLAY = False": "RUN_POINT_IN_TIME_REPLAY = True",
            "REPLAY_END_POSITION = None": "REPLAY_END_POSITION = 0",
        }
    )
    assert namespace["step_evidence"]["summary"]["timestamp"] == "2024-01-01T00:00:00Z"
