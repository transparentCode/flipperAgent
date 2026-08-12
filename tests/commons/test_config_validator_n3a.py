from __future__ import annotations

from typing import Any

from libs.common.config_validator import validate_config_alignment


class _Config:
    def __init__(self, state: dict[str, Any]) -> None:
        self.state = state

    def get(self, key: str, default: Any = None) -> Any:
        value: Any = self.state
        for part in key.split("."):
            if not isinstance(value, dict) or part not in value:
                return default
            value = value[part]
        return value


def _model_state(binding: dict[str, Any]) -> _Config:
    return _Config(
        {
            "models": {
                "assets": {
                    "BTCUSDT": {
                        "timeframes": {"1h": {"MeanReversionV2": {"enabled": True}}}
                    }
                }
            },
            "features": {"assets": {}},
            "signal": {"runtime": {"ohlcv_sources": {"BTCUSDT": binding}}},
            "ingestion": {
                "assets": {
                    "target_list": [],
                    "publish_timeframes": {"BTCUSDT": ["1h", "4h"]},
                }
            },
            "risk": {"assets": {}},
            "execution": {"assets": {}},
        }
    )


def test_validator_uses_ingestion_binding_instead_of_legacy_authority() -> None:
    warnings = validate_config_alignment(
        _model_state(
            {
                "source": "ingestion",
                "venue": "binance",
                "instrument_id": "BTC-USDT-PERP",
            }
        )
    )

    assert not any("ingestion.assets" in warning for warning in warnings)
    assert not any("publish_timeframes" in warning for warning in warnings)
    assert not any(
        "must use signal source ingestion" in warning for warning in warnings
    )


def test_validator_rejects_legacy_binding_for_active_model_asset() -> None:
    warnings = validate_config_alignment(
        _model_state(
            {
                "source": "legacy",
                "venue": "",
                "instrument_id": "",
            }
        )
    )

    assert any("must use signal source ingestion" in warning for warning in warnings)
    assert any("empty signal source venue" in warning for warning in warnings)
    assert any("empty signal source instrument_id" in warning for warning in warnings)
