import json

from libs.models.sr_v2.research.source import load_source_jsonl


def test_source_loader_binds_sha256(tmp_path, sr_v2_now):
    path = tmp_path / "source.jsonl"
    path.write_text(
        json.dumps(
            {
                "venue": "v",
                "instrument_id": "i",
                "asset": "a",
                "timeframe": "15m",
                "bar_open_at": "2024-01-01T00:00:00+00:00",
                "bar_close_at": "2024-01-01T00:15:00+00:00",
                "open": "1",
                "high": "2",
                "low": "0",
                "close": "1",
                "volume": "1",
                "source_identity": "one",
            }
        )
        + "\n"
    )
    manifest, records = load_source_jsonl(path)
    assert manifest.records == 1
    assert records[0].source_identity == "one"
