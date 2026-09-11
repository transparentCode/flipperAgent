"""L2-A1 deterministic research data contracts."""

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from libs.models.trendlines.config import load_trendlines_config
from libs.models.trendlines.signals.context import (
    BarAvailabilitySource,
    BarTimestampSemantics,
)
from libs.models.trendlines.workflows import research as research_module
from libs.models.trendlines.workflows.research import (
    TrendlineResearchDataMode,
    TrendlineResearchDataSpec,
    TrendlineResearchPurpose,
    TrendlineResearchSpec,
    generate_synthetic_frames,
    prepare_research_dataset,
    prepare_trendline_research,
)


def _synthetic_spec(seed: int = 42, *, timeframes: tuple[str, ...] = ("1h", "4h")):
    return TrendlineResearchSpec(
        purpose=TrendlineResearchPurpose.SMOKE,
        data=TrendlineResearchDataSpec(
            mode=TrendlineResearchDataMode.SYNTHETIC,
            seed=seed,
            start_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
            bar_counts={timeframe: 24 for timeframe in timeframes},
        ),
        asset="BTCUSDT",
        timeframes=timeframes,
        primary_timeframe=timeframes[0],
    )


def _frame(count: int = 4, *, offset: float = 0.0) -> pd.DataFrame:
    index = pd.date_range("2025-01-01", periods=count, freq="1h", tz="UTC")
    close = pd.Series([100.0 + offset + value for value in range(count)], index=index)
    frame = pd.DataFrame(
        {
            "open": close - 0.2,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": 100.0,
            "bar_available_at": index + pd.Timedelta(hours=1),
        },
        index=index,
    )
    frame.attrs["bar_timestamp_semantics"] = BarTimestampSemantics.OPEN_TIME.value
    frame.attrs["bar_availability_source"] = BarAvailabilitySource.FIXED_INTERVAL_DERIVED.value
    return frame


def _injected_spec(timeframes: tuple[str, ...] = ("1h", "4h")):
    return TrendlineResearchSpec(
        purpose=TrendlineResearchPurpose.RESEARCH,
        data=TrendlineResearchDataSpec(mode=TrendlineResearchDataMode.INJECTED),
        asset="BTCUSDT",
        timeframes=timeframes,
        primary_timeframe=timeframes[0],
    )


def test_synthetic_data_is_deterministic():
    first = generate_synthetic_frames(_synthetic_spec())
    second = generate_synthetic_frames(_synthetic_spec())

    for timeframe in first:
        pd.testing.assert_frame_equal(first[timeframe], second[timeframe])
        assert first[timeframe].attrs == second[timeframe].attrs


def test_different_synthetic_seed_changes_source_and_dataset_ids():
    first = asyncio.run(prepare_research_dataset(_synthetic_spec(seed=1)))
    second = asyncio.run(prepare_research_dataset(_synthetic_spec(seed=2)))

    assert first.source_refs["1h"].source_id != second.source_refs["1h"].source_id
    assert first.dataset_id != second.dataset_id


def test_synthetic_availability_follows_exact_timeframe_duration():
    frames = generate_synthetic_frames(_synthetic_spec(timeframes=("4h",)))
    frame = frames["4h"]

    assert (frame["bar_available_at"] - frame.index).eq(pd.Timedelta(hours=4)).all()


def test_injected_data_requires_every_requested_timeframe():
    with pytest.raises(ValueError, match="missing requested timeframes"):
        asyncio.run(
            prepare_research_dataset(
                _injected_spec(),
                loader={"1h": _frame()},
            )
        )


def test_unexpected_injected_timeframe_is_rejected():
    with pytest.raises(ValueError, match="unexpected timeframes"):
        asyncio.run(
            prepare_research_dataset(
                _injected_spec(timeframes=("1h",)),
                loader={"1h": _frame(), "4h": _frame()},
            )
        )


def test_conflicting_duplicate_event_rows_are_rejected():
    frame = _frame()
    duplicate = pd.concat([frame, frame.iloc[[0]].assign(high=999.0)])

    with pytest.raises(ValueError, match="ordered and unique"):
        asyncio.run(
            prepare_research_dataset(
                _injected_spec(timeframes=("1h",)),
                loader={"1h": duplicate},
            )
        )


def test_source_identity_is_computed_once_per_timeframe(monkeypatch):
    calls = 0
    original = research_module.data.resolve_source_ref

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(research_module.data, "resolve_source_ref", counted)
    asyncio.run(prepare_research_dataset(_synthetic_spec()))

    assert calls == 2


def test_dataset_identity_binds_all_timeframe_source_refs():
    first = asyncio.run(
        prepare_research_dataset(
            _injected_spec(),
            loader={"1h": _frame(), "4h": _frame(offset=10.0)},
        )
    )
    second = asyncio.run(
        prepare_research_dataset(
            _injected_spec(),
            loader={"1h": _frame(), "4h": _frame(offset=11.0)},
        )
    )

    assert first.dataset_id != second.dataset_id
    assert first.source_refs["1h"].source_id == second.source_refs["1h"].source_id


def test_research_preparation_performs_no_model_execution(monkeypatch):
    from libs.models.trendlines.pivots.fractal import FractalPivotExtractor

    def fail_if_called(*args, **kwargs):
        raise AssertionError("model execution must not occur during preparation")

    monkeypatch.setattr(FractalPivotExtractor, "extract", fail_if_called)
    run = asyncio.run(
        prepare_trendline_research(
            _synthetic_spec(timeframes=("1h",)),
            trendlines_config=load_trendlines_config(),
        )
    )

    assert run.dataset.frames["1h"].shape[0] == 24


def test_research_package_has_no_app_connector_notebook_or_viewer_dependency():
    root = Path(research_module.__file__).parent
    forbidden = ("app.connectors", "BinanceConnector", "jupyter", "IPython", "plotly", "TVLC")

    violations = [
        f"{path}: {token}"
        for path in root.rglob("*.py")
        for token in forbidden
        if token in path.read_text(encoding="utf-8")
    ]
    assert violations == []


def test_missing_timestamp_semantics_is_rejected():
    frame = _frame()
    frame.attrs.pop("bar_timestamp_semantics")

    with pytest.raises(ValueError, match="bar_timestamp_semantics metadata is required"):
        asyncio.run(
            prepare_research_dataset(
                _injected_spec(timeframes=("1h",)),
                loader={"1h": frame},
            )
        )


def test_open_time_availability_equal_to_event_time_is_rejected():
    frame = _frame()
    frame["bar_available_at"] = frame.index

    with pytest.raises(ValueError, match="strictly after event time"):
        asyncio.run(
            prepare_research_dataset(
                _injected_spec(timeframes=("1h",)),
                loader={"1h": frame},
            )
        )


def test_close_time_availability_differing_from_event_time_is_rejected():
    frame = _frame()
    frame.attrs["bar_timestamp_semantics"] = BarTimestampSemantics.CLOSE_TIME.value

    with pytest.raises(ValueError, match="equal to event time"):
        asyncio.run(
            prepare_research_dataset(
                _injected_spec(timeframes=("1h",)),
                loader={"1h": frame},
            )
        )


def test_identical_availability_schedules_have_stable_ids():
    first = asyncio.run(
        prepare_research_dataset(
            _injected_spec(timeframes=("1h",)),
            loader={"1h": _frame()},
        )
    )
    second = asyncio.run(
        prepare_research_dataset(
            _injected_spec(timeframes=("1h",)),
            loader={"1h": _frame()},
        )
    )

    assert first.source_refs["1h"].source_id == second.source_refs["1h"].source_id
    assert first.identity.availability_ids == second.identity.availability_ids
    assert first.dataset_id == second.dataset_id


def test_changed_availability_preserves_source_but_changes_dataset_identity():
    first_frame = _frame()
    second_frame = _frame()
    second_frame["bar_available_at"] = second_frame["bar_available_at"] + pd.Timedelta(
        minutes=1
    )

    first = asyncio.run(
        prepare_research_dataset(
            _injected_spec(timeframes=("1h",)),
            loader={"1h": first_frame},
        )
    )
    second = asyncio.run(
        prepare_research_dataset(
            _injected_spec(timeframes=("1h",)),
            loader={"1h": second_frame},
        )
    )

    assert first.source_refs["1h"].source_id == second.source_refs["1h"].source_id
    assert first.identity.availability_ids["1h"] != second.identity.availability_ids["1h"]
    assert first.dataset_id != second.dataset_id


def test_injected_mode_rejects_source_selection_fields():
    values = {
        "seed": 7,
        "start_time": datetime(2025, 1, 1, tzinfo=timezone.utc),
        "bar_counts": {"1h": 4},
        "event_start": datetime(2025, 1, 1, tzinfo=timezone.utc),
        "knowledge_cutoff": datetime(2025, 1, 2, tzinfo=timezone.utc),
    }

    for field, value in values.items():
        with pytest.raises(ValueError, match=f"{field}.*injected"):
            TrendlineResearchDataSpec(
                mode=TrendlineResearchDataMode.INJECTED,
                **{field: value},
            )


def test_binance_mode_rejects_synthetic_only_fields():
    values = {
        "seed": 7,
        "start_time": datetime(2025, 1, 1, tzinfo=timezone.utc),
        "bar_counts": {"1h": 4},
    }

    for field, value in values.items():
        with pytest.raises(ValueError, match=f"{field}.*binance"):
            TrendlineResearchDataSpec(
                mode=TrendlineResearchDataMode.BINANCE,
                event_start=datetime(2025, 1, 1, tzinfo=timezone.utc),
                knowledge_cutoff=datetime(2025, 1, 2, tzinfo=timezone.utc),
                **{field: value},
            )


def test_synthetic_mode_rejects_binance_only_fields():
    values = {
        "event_start": datetime(2025, 1, 1, tzinfo=timezone.utc),
        "knowledge_cutoff": datetime(2025, 1, 2, tzinfo=timezone.utc),
    }

    for field, value in values.items():
        with pytest.raises(ValueError, match=f"{field}.*synthetic"):
            TrendlineResearchDataSpec(
                mode=TrendlineResearchDataMode.SYNTHETIC,
                seed=7,
                start_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
                bar_counts={"1h": 4},
                **{field: value},
            )
