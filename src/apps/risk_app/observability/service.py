from __future__ import annotations

import time
from collections import defaultdict
from typing import Any

from libs.common.asset_manifest import AssetManifest, AssetManifestStore
from libs.common.config import ConfigManager
from libs.common.constants import CONFIG_FILE_MODELS
from libs.common.discovery import discover_assets
from libs.contracts.execution import OrderExecutionRequest
from libs.contracts.serialization import valkey_decode
from libs.risk.position_tracker import PositionTracker


class RiskObservabilityService:
    def __init__(
        self,
        db_pool: Any,
        redis_client: Any | None = None,
        manifest_store: AssetManifestStore | None = None,
        config_mgr: ConfigManager | None = None,
    ) -> None:
        self.db_pool = db_pool
        self.redis_client = redis_client
        self.manifest_store = manifest_store or (
            AssetManifestStore(redis_client) if redis_client is not None else None
        )
        if config_mgr is None:
            config_mgr = ConfigManager()
            config_mgr.register_file(CONFIG_FILE_MODELS)
        self.config_mgr = config_mgr

    async def health(self) -> dict[str, Any]:
        db_available = False
        valkey_available = False
        db_error: str | None = None
        valkey_error: str | None = None

        try:
            async with self.db_pool.acquire() as conn:
                await conn.fetchrow("SELECT 1")
            db_available = True
        except Exception as exc:
            db_error = str(exc)

        if self.redis_client is not None:
            try:
                valkey_available = bool(await self.redis_client.ping())
            except Exception as exc:
                valkey_error = str(exc)

        result: dict[str, Any] = {
            "status": "ok" if db_available else "degraded",
            "db_available": db_available,
            "valkey_available": valkey_available,
        }
        if db_error is not None:
            result["db_error"] = db_error
        if valkey_error is not None:
            result["valkey_error"] = valkey_error
        return result

    async def latest_orders(self, *, assets: list[str] | None = None) -> dict[str, Any]:
        if self.redis_client is None:
            return {
                "status": "error",
                "error": "valkey client unavailable",
                "count": 0,
                "items": [],
            }

        asset_list = await self._resolve_assets(assets)
        now_ms = int(time.time() * 1000)
        items = [await self._read_latest_order(asset, now_ms=now_ms) for asset in asset_list]
        ok_count = sum(1 for item in items if item["status"] == "ok")
        no_data_count = sum(1 for item in items if item["status"] == "no_data")
        error_count = sum(1 for item in items if item["status"] == "error")
        status = "ok" if ok_count > 0 else "no_data"
        if error_count and ok_count == 0 and no_data_count == 0:
            status = "error"
        return {
            "status": status,
            "count": len(items),
            "ok_count": ok_count,
            "no_data_count": no_data_count,
            "error_count": error_count,
            "items": items,
        }

    async def account_snapshot(self) -> dict[str, Any]:
        now_ms = int(time.time() * 1000)
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT timestamp, balance, equity, unrealized_pnl, realized_pnl,
                           drawdown_pct, peak_equity, open_position_count, daily_pnl
                    FROM risk_account_snapshots
                    ORDER BY timestamp DESC
                    LIMIT 1
                    """
                )
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

        if not row:
            return {"status": "no_data"}

        ts = float(row["timestamp"])
        ts_ms = ts * 1000 if ts < 1e12 else ts
        snapshot = {
            "timestamp": ts,
            "balance": float(row["balance"]),
            "equity": float(row["equity"]),
            "unrealized_pnl": float(row["unrealized_pnl"]),
            "realized_pnl": float(row["realized_pnl"]),
            "drawdown_pct": float(row["drawdown_pct"]),
            "peak_equity": float(row["peak_equity"]),
            "open_position_count": int(row["open_position_count"]),
            "daily_pnl": float(row["daily_pnl"]),
        }
        return {
            "status": "ok",
            "lag_ms": now_ms - int(ts_ms),
            "snapshot": snapshot,
        }

    async def open_positions(self, *, asset: str | None = None) -> dict[str, Any]:
        try:
            tracker = await PositionTracker.load_positions(self.db_pool)
        except Exception as exc:
            return {"status": "error", "error": str(exc), "count": 0, "positions": []}

        normalized_asset = asset.upper().strip() if asset else None
        positions = [
            position.model_dump(mode="json")
            for position in tracker.all_positions()
            if normalized_asset is None or position.asset == normalized_asset
        ]
        return {
            "status": "ok" if positions else "no_data",
            "count": len(positions),
            "positions": positions,
        }

    async def status(self) -> dict[str, Any]:
        manifests = await self._load_manifests()
        latest_orders = await self.latest_orders(
            assets=[manifest.symbol for manifest in manifests] if manifests else None,
        )

        try:
            tracker = await PositionTracker.load_positions(self.db_pool)
            positions = tracker.all_positions()
        except Exception as exc:
            return {
                "status": "error",
                "error": str(exc),
                "count": 0,
                "assets": [],
            }

        positions_by_asset: dict[str, list[Any]] = defaultdict(list)
        for position in positions:
            positions_by_asset[position.asset].append(position)

        order_items = {
            item["asset"]: item
            for item in latest_orders.get("items", [])
        }
        manifest_by_asset = {manifest.symbol: manifest for manifest in manifests}
        asset_names = sorted(set(manifest_by_asset) | set(positions_by_asset) | set(order_items))

        assets: list[dict[str, Any]] = []
        for asset in asset_names:
            manifest = manifest_by_asset.get(asset)
            asset_positions = positions_by_asset.get(asset, [])
            gross_exposure = sum(abs(position.size * position.current_price) for position in asset_positions)
            net_exposure = sum(position.size * position.current_price * position.direction for position in asset_positions)
            assets.append(
                {
                    "asset": asset,
                    "enabled": manifest.enabled if manifest is not None else None,
                    "desired_state": manifest.desired_state if manifest is not None else None,
                    "provider": manifest.provider if manifest is not None else None,
                    "base_timeframe": manifest.base_timeframe if manifest is not None else None,
                    "publish_timeframes": list(manifest.publish_timeframes) if manifest is not None else [],
                    "position_count": len(asset_positions),
                    "gross_exposure": gross_exposure,
                    "net_exposure": net_exposure,
                    "latest_order": order_items.get(asset),
                }
            )

        return {
            "status": "ok" if assets else "no_data",
            "count": len(assets),
            "assets": assets,
        }

    async def summary(self) -> dict[str, Any]:
        account = await self.account_snapshot()
        orders = await self.latest_orders()
        positions = await self.open_positions()
        return {
            "account": account,
            "orders": {
                "status": orders.get("status"),
                "count": orders.get("count", 0),
                "ok_count": orders.get("ok_count", 0),
                "no_data_count": orders.get("no_data_count", 0),
                "error_count": orders.get("error_count", 0),
            },
            "positions": {
                "status": positions.get("status"),
                "count": positions.get("count", 0),
            },
        }

    async def _resolve_assets(self, requested_assets: list[str] | None) -> list[str]:
        if requested_assets:
            seen: set[str] = set()
            normalized: list[str] = []
            for asset in requested_assets:
                value = str(asset).upper().strip()
                if value and value not in seen:
                    seen.add(value)
                    normalized.append(value)
            return normalized

        manifests = await self._load_manifests()
        if manifests:
            return [manifest.symbol for manifest in manifests]

        seen = set()
        assets: list[str] = []
        for asset in discover_assets(self.config_mgr):
            normalized = str(asset).upper().strip()
            if normalized and normalized not in seen:
                seen.add(normalized)
                assets.append(normalized)
        return assets

    async def _load_manifests(self) -> list[AssetManifest]:
        if self.manifest_store is None:
            return []
        try:
            return await self.manifest_store.list_assets()
        except Exception:
            return []

    async def _read_latest_order(self, asset: str, *, now_ms: int) -> dict[str, Any]:
        stream = f"orders:{asset}"
        try:
            messages = await self.redis_client.xrevrange(stream, count=1)
        except Exception as exc:
            return {
                "asset": asset,
                "stream": stream,
                "status": "error",
                "error": str(exc),
            }

        if not messages:
            return {
                "asset": asset,
                "stream": stream,
                "status": "no_data",
            }

        message_id, payload = messages[0]
        decoded = valkey_decode(dict(payload), OrderExecutionRequest)
        lag_ms = self._compute_lag_ms(decoded.timestamp, now_ms)
        return {
            "asset": asset,
            "stream": stream,
            "message_id": message_id.decode() if isinstance(message_id, bytes) else str(message_id),
            "timestamp": decoded.timestamp,
            "lag_ms": lag_ms,
            "status": "ok",
            "side": decoded.side,
            "size": decoded.size,
            "order_type": decoded.order_type,
            "requested_price": decoded.requested_price,
            "stop_loss_price": decoded.stop_loss_price,
            "take_profit_price": decoded.take_profit_price,
            "model_name": decoded.model_name,
            "source_timeframe": decoded.source_timeframe,
            "idempotency_key": decoded.idempotency_key,
            "close_reason": decoded.close_reason,
            "metadata": decoded.metadata,
        }

    @staticmethod
    def _compute_lag_ms(timestamp: float, now_ms: int) -> int | None:
        try:
            ts = float(timestamp)
        except (TypeError, ValueError):
            return None
        ts_ms = ts * 1000 if ts < 1e12 else ts
        return now_ms - int(ts_ms)
