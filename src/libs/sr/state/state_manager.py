"""Redis-backed persistence for canonical v2 S/R state.

This module persists ``ManagedZone`` and ``ScoredLevel`` snapshots using a
small JSON schema that is stable across process restarts. ``SRStateManager``
remains as a deprecated compatibility alias for external callers still using
the old name, but the stored model shape is now v2-native.
"""

from __future__ import annotations

import json
import logging
import warnings
from dataclasses import asdict, fields
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional, Protocol

from app.sr.lifecycle.state_machine import ManagedZone
from app.sr.models import (
    CandidateLevel,
    LevelFeatureVector,
    LevelType,
    ScoredLevel,
    ZoneLifecycleEvent,
    ZoneStatus,
)

logger = logging.getLogger("app.sr")

_LEVEL_FEATURE_FIELDS = {field.name for field in fields(LevelFeatureVector)}


class RedisLike(Protocol):
    def set(self, key: str, value: str, ex: Optional[int] = None) -> Any: ...
    def get(self, key: str) -> Any: ...
    def delete(self, *keys: str) -> Any: ...


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _encode_datetime(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value is not None else None


def _decode_datetime(value: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(value) if value else None


def _load_json(raw: Any) -> Optional[Dict[str, Any]]:
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return json.loads(raw)


class ZoneStateStore:
    """Persist v2 zone and scored-level snapshots to Redis-compatible storage."""

    KEY_ZONES = "sr:{symbol}:zones"
    KEY_LEVELS = "sr:{symbol}:levels:{timeframe}"
    KEY_LEVEL_INDEX = "sr:{symbol}:level_timeframes"
    KEY_META = "sr:{symbol}:meta"
    DEFAULT_TTL = 86400
    SCHEMA_VERSION = 2

    def __init__(self, redis_handler: RedisLike, ttl: int = DEFAULT_TTL):
        self.redis = redis_handler
        self.ttl = ttl

    def snapshot_zones(
        self,
        symbol: str,
        zones: List[ManagedZone],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Persist ``ManagedZone`` snapshots for one asset."""
        try:
            payload = {
                "schema_version": self.SCHEMA_VERSION,
                "zones": [self._zone_to_dict(zone) for zone in zones],
                "count": len(zones),
                "timestamp": _encode_datetime(_now_utc()),
                "metadata": metadata or {},
            }
            self.redis.set(
                self.KEY_ZONES.format(symbol=symbol),
                json.dumps(payload),
                ex=self.ttl,
            )

            meta_payload = {
                "schema_version": self.SCHEMA_VERSION,
                "zone_count": len(zones),
                "support_count": sum(1 for zone in zones if zone.level_type == LevelType.SUPPORT),
                "resistance_count": sum(1 for zone in zones if zone.level_type == LevelType.RESISTANCE),
                "last_update": _encode_datetime(_now_utc()),
            }
            self.redis.set(
                self.KEY_META.format(symbol=symbol),
                json.dumps(meta_payload),
                ex=self.ttl,
            )
            logger.debug("ZoneStateStore: Saved %s zones for %s", len(zones), symbol)
            return True
        except Exception as exc:
            logger.error("ZoneStateStore: Failed to snapshot %s: %s", symbol, exc)
            return False

    def restore_zones(self, symbol: str) -> Optional[List[ManagedZone]]:
        """Load persisted ``ManagedZone`` snapshots for one asset."""
        try:
            payload = _load_json(self.redis.get(self.KEY_ZONES.format(symbol=symbol)))
            if not payload:
                return None
            if not self._is_supported_schema(payload, f"zone payload for {symbol}"):
                return None

            zones = self._restore_records(
                payload.get("zones", []),
                self._dict_to_zone,
                f"zone payload for {symbol}",
            )
            logger.debug("ZoneStateStore: Restored %s zones for %s", len(zones), symbol)
            return zones
        except Exception as exc:
            logger.error("ZoneStateStore: Failed to restore %s: %s", symbol, exc)
            return None

    def snapshot_scored_levels(
        self,
        symbol: str,
        timeframe: str,
        levels: List[ScoredLevel],
    ) -> bool:
        """Persist canonical ``ScoredLevel`` data for one asset/timeframe pair."""
        try:
            payload = {
                "schema_version": self.SCHEMA_VERSION,
                "levels": [self._scored_level_to_dict(level) for level in levels],
                "count": len(levels),
                "timeframe": timeframe,
                "timestamp": _encode_datetime(_now_utc()),
            }
            self.redis.set(
                self.KEY_LEVELS.format(symbol=symbol, timeframe=timeframe),
                json.dumps(payload),
                ex=self.ttl,
            )
            self._remember_level_timeframe(symbol, timeframe)
            logger.debug(
                "ZoneStateStore: Saved %s scored levels for %s/%s",
                len(levels),
                symbol,
                timeframe,
            )
            return True
        except Exception as exc:
            logger.error(
                "ZoneStateStore: Failed to snapshot scored levels %s/%s: %s",
                symbol,
                timeframe,
                exc,
            )
            return False

    def restore_scored_levels(
        self,
        symbol: str,
        timeframe: str,
    ) -> Optional[List[ScoredLevel]]:
        """Load persisted ``ScoredLevel`` data for one asset/timeframe pair."""
        try:
            payload = _load_json(
                self.redis.get(self.KEY_LEVELS.format(symbol=symbol, timeframe=timeframe)),
            )
            if not payload:
                return None
            if not self._is_supported_schema(payload, f"scored-level payload for {symbol}/{timeframe}"):
                return None

            return self._restore_records(
                payload.get("levels", []),
                self._dict_to_scored_level,
                f"scored-level payload for {symbol}/{timeframe}",
            )
        except Exception as exc:
            logger.error(
                "ZoneStateStore: Failed to restore scored levels %s/%s: %s",
                symbol,
                timeframe,
                exc,
            )
            return None

    def get_metadata(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get stored zone metadata without loading full zone payloads."""
        try:
            return _load_json(self.redis.get(self.KEY_META.format(symbol=symbol)))
        except Exception as exc:
            logger.error("ZoneStateStore: Failed to load metadata for %s: %s", symbol, exc)
            return None

    def clear(self, symbol: str) -> bool:
        """Clear stored zone metadata and zone snapshots for one asset."""
        try:
            level_keys = [
                self.KEY_LEVELS.format(symbol=symbol, timeframe=timeframe)
                for timeframe in self._load_level_timeframes(symbol)
            ]
            self.redis.delete(
                self.KEY_ZONES.format(symbol=symbol),
                self.KEY_META.format(symbol=symbol),
                self.KEY_LEVEL_INDEX.format(symbol=symbol),
                *level_keys,
            )
            logger.debug("ZoneStateStore: Cleared state for %s", symbol)
            return True
        except Exception as exc:
            logger.error("ZoneStateStore: Failed to clear %s: %s", symbol, exc)
            return False

    # ------------------------------------------------------------------
    # Compatibility wrappers
    # ------------------------------------------------------------------

    def snapshot(
        self,
        symbol: str,
        zones: List[ManagedZone],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        return self.snapshot_zones(symbol, zones, metadata)

    def restore(self, symbol: str) -> Optional[List[ManagedZone]]:
        return self.restore_zones(symbol)

    def snapshot_levels(
        self,
        symbol: str,
        timeframe: str,
        levels: List[ScoredLevel],
    ) -> bool:
        return self.snapshot_scored_levels(symbol, timeframe, levels)

    def restore_levels(
        self,
        symbol: str,
        timeframe: str,
    ) -> Optional[List[ScoredLevel]]:
        return self.restore_scored_levels(symbol, timeframe)

    # ------------------------------------------------------------------
    # Serialization helpers
    # ------------------------------------------------------------------

    def _remember_level_timeframe(self, symbol: str, timeframe: str) -> None:
        key = self.KEY_LEVEL_INDEX.format(symbol=symbol)
        tracked = self._load_level_timeframes(symbol)
        if timeframe in tracked:
            return

        payload = {
            "schema_version": self.SCHEMA_VERSION,
            "timeframes": sorted([*tracked, timeframe]),
            "timestamp": _encode_datetime(_now_utc()),
        }
        encoded = json.dumps(payload)

        # Try atomic WATCH/MULTI if available, else plain SET
        try:
            with self.redis.pipeline() as pipe:
                pipe.watch(key)
                pipe.multi()
                pipe.set(key, encoded, ex=self.ttl)
                pipe.execute()
        except AttributeError:
            # Redis stub or client without pipeline support
            self.redis.set(key, encoded, ex=self.ttl)
        except Exception:
            # WatchError or connection issue — best-effort fallback
            self.redis.set(key, encoded, ex=self.ttl)

    def _load_level_timeframes(self, symbol: str) -> List[str]:
        payload = _load_json(self.redis.get(self.KEY_LEVEL_INDEX.format(symbol=symbol)))
        if not payload:
            return []
        if not self._is_supported_schema(payload, f"level index for {symbol}"):
            return []

        raw_timeframes = payload.get("timeframes", [])
        if not isinstance(raw_timeframes, list):
            logger.warning(
                "ZoneStateStore: Ignoring malformed timeframe index for %s",
                symbol,
            )
            return []
        return [str(timeframe) for timeframe in raw_timeframes if timeframe]

    def _is_supported_schema(self, payload: Dict[str, Any], context: str) -> bool:
        schema_version = payload.get("schema_version")
        if schema_version in (None, self.SCHEMA_VERSION):
            return True

        logger.warning(
            "ZoneStateStore: Skipping %s with unsupported schema_version=%s",
            context,
            schema_version,
        )
        return False

    def _restore_records(self, raw_items: Any, loader, context: str) -> List[Any]:
        if not isinstance(raw_items, list):
            logger.warning("ZoneStateStore: Skipping malformed %s (expected list)", context)
            return []

        restored: List[Any] = []
        for index, item in enumerate(raw_items):
            try:
                restored.append(loader(item))
            except Exception as exc:
                logger.warning(
                    "ZoneStateStore: Skipping invalid %s[%s]: %s",
                    context,
                    index,
                    exc,
                )
        return restored

    def _zone_to_dict(self, zone: ManagedZone) -> Dict[str, Any]:
        return {
            "zone_id": zone.zone_id,
            "scored_level": self._scored_level_to_dict(zone.scored_level),
            "status": zone.status.name,
            "strength": zone.strength,
            "touch_count": zone.touch_count,
            "bars_since_formation": zone.bars_since_formation,
            "bars_since_last_touch": zone.bars_since_last_touch,
            "bars_since_break": zone.bars_since_break,
            "breakout_direction": zone.breakout_direction,
            "false_breakout_count": zone.false_breakout_count,
            "events": [self._event_to_dict(event) for event in zone.events[-100:]],
            "detection_timestamp": _encode_datetime(zone.detection_timestamp),
            "reinforcement_timestamp": _encode_datetime(zone.reinforcement_timestamp),
            "contributing_kernels": list(zone.contributing_kernels),
            "hold_probability": zone.hold_probability,
            "resilience": zone.resilience,
            "_touches_held": zone._touches_held,
            "_touches_broken": zone._touches_broken,
        }

    def _dict_to_zone(self, data: Dict[str, Any]) -> ManagedZone:
        zone = ManagedZone(
            zone_id=data.get("zone_id", ""),
            scored_level=self._dict_to_scored_level(data.get("scored_level", {})),
            status=ZoneStatus[data.get("status", ZoneStatus.FORMING.name)],
            strength=data.get("strength", 0.0),
            touch_count=data.get("touch_count", 0),
            bars_since_formation=data.get("bars_since_formation", 0),
            bars_since_last_touch=data.get("bars_since_last_touch", 0),
            bars_since_break=data.get("bars_since_break", 0),
            breakout_direction=data.get("breakout_direction"),
            false_breakout_count=data.get("false_breakout_count", 0),
            events=self._restore_records(
                data.get("events", []),
                self._dict_to_event,
                f"events for zone {data.get('zone_id', '')}",
            ),
            detection_timestamp=_decode_datetime(data.get("detection_timestamp")),
            reinforcement_timestamp=_decode_datetime(data.get("reinforcement_timestamp")),
            contributing_kernels=list(data.get("contributing_kernels", [])),
            hold_probability=data.get("hold_probability", 0.5),
            resilience=data.get("resilience", 0.0),
        )
        zone._touches_held = data.get("_touches_held", 0)
        zone._touches_broken = data.get("_touches_broken", 0)
        return zone

    def _scored_level_to_dict(self, level: ScoredLevel) -> Dict[str, Any]:
        return {
            "candidate": self._candidate_to_dict(level.candidate),
            "features": self._feature_vector_to_dict(level.features),
            "strength": level.strength,
            "confidence": level.confidence,
            "contributing_kernels": list(level.contributing_kernels),
            "ensemble_method": level.ensemble_method,
            "zone_quality": level.zone_quality,
            "confluence_tier": level.confluence_tier,
        }

    def _dict_to_scored_level(self, data: Dict[str, Any]) -> ScoredLevel:
        return ScoredLevel(
            candidate=self._dict_to_candidate(data.get("candidate", {})),
            features=self._dict_to_feature_vector(data.get("features", {})),
            strength=data.get("strength", 0.0),
            confidence=data.get("confidence", 0.0),
            contributing_kernels=list(data.get("contributing_kernels", [])),
            ensemble_method=data.get("ensemble_method", "weighted_average"),
            zone_quality=data.get("zone_quality", 0.0),
            confluence_tier=data.get("confluence_tier", "C"),
        )

    def _candidate_to_dict(self, candidate: CandidateLevel) -> Dict[str, Any]:
        return {
            "center_price": candidate.center_price,
            "lower_bound": candidate.lower_bound,
            "upper_bound": candidate.upper_bound,
            "level_type": candidate.level_type.name,
            "kernel_name": candidate.kernel_name,
            "timeframe": candidate.timeframe,
            "raw_score": candidate.raw_score,
            "metadata": candidate.metadata,
            "timestamp": _encode_datetime(candidate.timestamp),
            "atr_at_detection": candidate.atr_at_detection,
        }

    def _dict_to_candidate(self, data: Dict[str, Any]) -> CandidateLevel:
        return CandidateLevel(
            center_price=data.get("center_price", 0.0),
            lower_bound=data.get("lower_bound", 0.0),
            upper_bound=data.get("upper_bound", 0.0),
            level_type=LevelType[data.get("level_type", LevelType.SUPPORT.name)],
            kernel_name=data.get("kernel_name", ""),
            timeframe=data.get("timeframe", ""),
            raw_score=data.get("raw_score", 0.0),
            metadata=data.get("metadata", {}),
            timestamp=_decode_datetime(data.get("timestamp")) or _now_utc(),
            atr_at_detection=data.get("atr_at_detection", 0.0),
        )

    def _feature_vector_to_dict(self, features: LevelFeatureVector) -> Dict[str, Any]:
        return asdict(features)

    def _dict_to_feature_vector(self, data: Dict[str, Any]) -> LevelFeatureVector:
        filtered = {
            key: value
            for key, value in data.items()
            if key in _LEVEL_FEATURE_FIELDS
        }
        return LevelFeatureVector(**filtered)

    def _event_to_dict(self, event: ZoneLifecycleEvent) -> Dict[str, Any]:
        return {
            "zone_id": event.zone_id,
            "timestamp": _encode_datetime(event.timestamp),
            "from_state": event.from_state.name,
            "to_state": event.to_state.name,
            "trigger": event.trigger,
            "price_at_event": event.price_at_event,
            "volume_at_event": event.volume_at_event,
            "bar_index": event.bar_index,
            "metadata": event.metadata,
        }

    def _dict_to_event(self, data: Dict[str, Any]) -> ZoneLifecycleEvent:
        return ZoneLifecycleEvent(
            zone_id=data.get("zone_id", ""),
            timestamp=_decode_datetime(data.get("timestamp")) or _now_utc(),
            from_state=ZoneStatus[data.get("from_state", ZoneStatus.FORMING.name)],
            to_state=ZoneStatus[data.get("to_state", ZoneStatus.FORMING.name)],
            trigger=data.get("trigger", ""),
            price_at_event=data.get("price_at_event", 0.0),
            volume_at_event=data.get("volume_at_event", 0.0),
            bar_index=data.get("bar_index", 0),
            metadata=data.get("metadata", {}),
        )


class SRStateManager(ZoneStateStore):
    """Deprecated alias for the canonical v2 ``ZoneStateStore``."""

    def __init__(self, redis_handler: RedisLike, ttl: int = ZoneStateStore.DEFAULT_TTL):
        warnings.warn(
            "SRStateManager is deprecated. Use ZoneStateStore for v2 ManagedZone and ScoredLevel persistence.",
            DeprecationWarning,
            stacklevel=2,
        )
        super().__init__(redis_handler, ttl=ttl)
