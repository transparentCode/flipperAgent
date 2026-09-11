"""Strict byte-preserving research-frame artifact tests."""

import asyncio
import base64
import json
from datetime import timezone
from pathlib import Path

import pandas as pd
import pytest

from libs.models.trendlines.signals.context import (
    BarAvailabilitySource,
    BarTimestampSemantics,
)
from libs.models.trendlines.workflows.research import (
    FRAME_ARTIFACT_SEMANTICS_VERSION,
    TrendlineFrameArtifactError,
    TrendlineResearchDataMode,
    TrendlineResearchDataSpec,
    TrendlineResearchPurpose,
    TrendlineResearchSpec,
    read_research_frame_artifact,
    prepare_research_dataset,
    write_research_frame_artifact,
)


def _frame(count: int = 4) -> pd.DataFrame:
    index = pd.date_range(
        "2025-01-01",
        periods=count,
        freq="1h",
        tz=timezone.utc,
    ).as_unit("ms").rename("timestamp")
    availability = (index + pd.Timedelta(hours=1)).as_unit("ms").rename(
        "bar_available_at"
    )
    close = pd.Series(
        [100.0 + value for value in range(count)],
        index=index,
        dtype="float64",
    )
    frame = pd.DataFrame(
        {
            "open": close - 0.2,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": pd.Series(100.0, index=index, dtype="float64"),
        },
        index=index,
    )
    frame["bar_available_at"] = pd.Series(availability, index=index, name=availability.name)
    frame.attrs["bar_timestamp_semantics"] = BarTimestampSemantics.OPEN_TIME.value
    frame.attrs["bar_availability_source"] = BarAvailabilitySource.FIXED_INTERVAL_DERIVED.value
    return frame


def _spec() -> TrendlineResearchDataSpec:
    return TrendlineResearchDataSpec(mode=TrendlineResearchDataMode.INJECTED)


def _identities(frame: pd.DataFrame) -> tuple[str, str, str]:
    prepared = asyncio.run(
        prepare_research_dataset(
            TrendlineResearchSpec(
                purpose=TrendlineResearchPurpose.RESEARCH,
                data=_spec(),
                asset="BTCUSDT",
                timeframes=("1h",),
                primary_timeframe="1h",
            ),
            loader={"1h": frame},
        )
    )
    return (
        prepared.source_refs["1h"].source_id,
        prepared.identity.availability_ids["1h"],
        prepared.dataset_id,
    )


def _write(frame: pd.DataFrame, path: Path) -> tuple[str, str, str]:
    source_id, availability_id, dataset_id = _identities(frame)
    write_research_frame_artifact(
        frame,
        asset="BTCUSDT",
        timeframe="1h",
        data_spec=_spec(),
        source_id=source_id,
        availability_id=availability_id,
        dataset_id=dataset_id,
        output_path=path,
    )
    return source_id, availability_id, dataset_id


def _rewrite(path: Path, mutate) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutate(payload)
    path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")


def test_named_millisecond_utc_index_round_trips_exactly(tmp_path: Path):
    frame = _frame()
    identities = _write(frame, tmp_path / "frame.json")

    recovered = read_research_frame_artifact(
        tmp_path / "frame.json",
        expected_asset="BTCUSDT",
        expected_timeframe="1h",
        expected_source_id=identities[0],
        expected_availability_id=identities[1],
        expected_dataset_id=identities[2],
    )

    pd.testing.assert_frame_equal(frame, recovered, check_freq=False)
    assert str(recovered.index.dtype) == "datetime64[ms, UTC]"
    assert recovered.index.name == "timestamp"


def test_float64_bytes_and_column_order_round_trip_exactly(tmp_path: Path):
    frame = _frame()
    _write(frame, tmp_path / "frame.json")
    payload = json.loads((tmp_path / "frame.json").read_text(encoding="utf-8"))

    assert payload["column_order"] == ["open", "high", "low", "close", "volume", "bar_available_at"]
    assert [item["name"] for item in payload["columns"]] == payload["column_order"][:-1]
    assert all(item["numpy_dtype"] == "float64" for item in payload["columns"])
    assert all(item["pandas_dtype"] == "float64" for item in payload["columns"])
    for item, name in zip(payload["columns"], payload["column_order"][:-1]):
        raw = base64.b64decode(item["bytes_base64"])
        assert raw == frame[name].to_numpy(copy=False).tobytes(order="C")


def test_availability_resolution_round_trips_exactly(tmp_path: Path):
    frame = _frame()
    _write(frame, tmp_path / "frame.json")
    recovered = read_research_frame_artifact(tmp_path / "frame.json")
    availability = pd.DatetimeIndex(recovered["bar_available_at"])

    assert str(availability.dtype) == "datetime64[ms, UTC]"
    assert availability.name == "bar_available_at"
    assert availability.asi8.tolist() == pd.DatetimeIndex(frame["bar_available_at"]).asi8.tolist()


def test_source_availability_and_dataset_ids_remain_stable(tmp_path: Path):
    frame = _frame()
    expected = _write(frame, tmp_path / "frame.json")
    recovered = read_research_frame_artifact(tmp_path / "frame.json")
    actual = _identities(recovered)

    assert actual == expected


def test_missing_index_name_is_rejected(tmp_path: Path):
    frame = _frame()
    frame.index = frame.index.rename(None)
    with pytest.raises(TrendlineFrameArtifactError, match="index.name"):
        _write(frame, tmp_path / "frame.json")


def test_changed_timestamp_unit_is_rejected(tmp_path: Path):
    path = tmp_path / "frame.json"
    _write(_frame(), path)
    _rewrite(path, lambda payload: payload["index"].update({"unit": "ns"}))
    with pytest.raises(TrendlineFrameArtifactError, match="artifact_id|dtype"):
        read_research_frame_artifact(path)


def test_changed_numeric_dtype_is_rejected(tmp_path: Path):
    path = tmp_path / "frame.json"
    _write(_frame(), path)

    def change_dtype(payload):
        payload["columns"][0]["pandas_dtype"] = "float32"
        without_id = dict(payload)
        without_id.pop("artifact_id")
        from libs.models.trendlines.contracts.identity import canonical_hash

        payload["artifact_id"] = canonical_hash(
            without_id,
            semantics_version=FRAME_ARTIFACT_SEMANTICS_VERSION,
        )

    _rewrite(path, change_dtype)
    with pytest.raises(TrendlineFrameArtifactError, match="pandas_dtype"):
        read_research_frame_artifact(path)


def test_tampered_encoded_bytes_or_artifact_id_is_rejected(tmp_path: Path):
    path = tmp_path / "frame.json"
    _write(_frame(), path)

    def change_bytes(payload):
        encoded = payload["columns"][0]["bytes_base64"]
        payload["columns"][0]["bytes_base64"] = ("A" if encoded[0] != "A" else "B") + encoded[1:]

    _rewrite(path, change_bytes)
    with pytest.raises(TrendlineFrameArtifactError, match="artifact_id"):
        read_research_frame_artifact(path)

    _write(_frame(), path)
    _rewrite(path, lambda payload: payload.update({"artifact_id": "0" * 64}))
    with pytest.raises(TrendlineFrameArtifactError, match="artifact_id"):
        read_research_frame_artifact(path)
