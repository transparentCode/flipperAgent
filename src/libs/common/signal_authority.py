"""Atomic route ownership and signal-publication guards for D11B.

The migration is intentionally a small Valkey contract.  The authority hash
and the guarded XADD scripts are the only shared coordination primitive; no
worker, daemon, or registry is introduced here.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

SignalOwner = Literal["strategy", "decision"]

TARGET_SIGNAL_ROUTES: tuple[str, ...] = (
    "BTCUSDT:1h",
    "BTCUSDT:4h",
    "ETHUSDT:4h",
)

_AUTHORITY_FIELDS = ("schema_version", "route", "owner", "epoch", "boundary_ms")


class SignalAuthorityError(RuntimeError):
    """The authority contract is absent, malformed, or unavailable."""


class SignalAuthorityConflict(SignalAuthorityError):
    """An atomic owner transfer could not validate its complete precondition."""


@dataclass(frozen=True, slots=True)
class SignalRouteAuthority:
    schema_version: int
    route: str
    owner: SignalOwner
    epoch: int
    boundary_ms: int

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("signal authority schema_version must be 1")
        normalized = normalize_signal_route(self.route)
        if normalized != self.route:
            raise ValueError("signal authority route is not canonical")
        if not isinstance(self.owner, str) or self.owner not in {
            "strategy",
            "decision",
        }:
            raise ValueError("signal authority owner is not supported")
        if (
            isinstance(self.epoch, bool)
            or not isinstance(self.epoch, int)
            or self.epoch < 0
        ):
            raise ValueError("signal authority epoch must be a non-negative integer")
        if (
            isinstance(self.boundary_ms, bool)
            or not isinstance(self.boundary_ms, int)
            or self.boundary_ms < 0
        ):
            raise ValueError("signal authority boundary_ms must be non-negative")


@dataclass(frozen=True, slots=True)
class GuardedSignalWrite:
    allowed: bool
    managed: bool
    stream_id: str | None = None
    reason: str | None = None
    outcome: Literal["PUBLISHED", "EXISTING", "CONFLICT", "DENIED"] = "PUBLISHED"
    existing_fields: Mapping[str, str] | None = None


def _validate_owner(owner: object, *, field_name: str = "owner") -> SignalOwner:
    if not isinstance(owner, str) or owner not in {"strategy", "decision"}:
        raise ValueError(f"{field_name} must be strategy or decision")
    return owner  # type: ignore[return-value]


def normalize_signal_route(route: str) -> str:
    if not isinstance(route, str) or not route.strip():
        raise TypeError("signal route must be non-empty text")
    value = route.strip()
    if value.count(":") != 1:
        raise ValueError("signal route must be ASSET:TIMEFRAME")
    asset, timeframe = value.split(":", 1)
    if not asset or not timeframe or asset != asset.upper():
        raise ValueError("signal route asset must be canonical uppercase text")
    if any(not (char.isalnum() or char in "_-") for char in asset):
        raise ValueError("signal route asset contains unsupported characters")
    if any(char.isspace() for char in timeframe) or ":" in timeframe:
        raise ValueError("signal route timeframe is malformed")
    return f"{asset}:{timeframe}"


def signal_authority_key(route: str) -> str:
    return f"signal:authority:{normalize_signal_route(route)}"


def signal_route_from_stream(stream_key: str) -> str:
    if not isinstance(stream_key, str) or not stream_key.startswith("signals:"):
        raise ValueError("signal stream key must start with signals:")
    return normalize_signal_route(stream_key.removeprefix("signals:"))


_SEED_SCRIPT = r"""
local n = tonumber(ARGV[1])
for i = 1, n do
  local key = KEYS[i]
  local route = ARGV[i + 1]
  local count = redis.call('HLEN', key)
  if count == 0 then
    -- validated in the read-only pass; creation happens below
  elseif count ~= 5 then
    return {0, 'malformed authority record: ' .. route}
  else
    if redis.call('HGET', key, 'schema_version') ~= '1'
      or redis.call('HGET', key, 'route') ~= route
      or redis.call('HGET', key, 'owner') ~= 'strategy'
      or tonumber(redis.call('HGET', key, 'epoch')) == nil
      or tonumber(redis.call('HGET', key, 'boundary_ms')) == nil then
      return {0, 'authority record is not an exact strategy record: ' .. route}
    end
  end
end
for i = 1, n do
  local key = KEYS[i]
  local route = ARGV[i + 1]
  if redis.call('HLEN', key) == 0 then
    redis.call('HSET', key,
      'schema_version', '1',
      'route', route,
      'owner', 'strategy',
      'epoch', '0',
      'boundary_ms', '0')
  end
end
return {1, 'OK'}
"""


_HANDOFF_SCRIPT = r"""
local n = tonumber(ARGV[1])
local expected_owner = ARGV[2]
local new_owner = ARGV[3]
for i = 1, n do
  local key = KEYS[i]
  local route = ARGV[3 + i]
  local expected_epoch = ARGV[3 + n + i]
  local next_boundary_ms = tonumber(ARGV[3 + 2 * n + i])
  local owner = redis.call('HGET', key, 'owner')
  local epoch = redis.call('HGET', key, 'epoch')
  local boundary_ms = tonumber(redis.call('HGET', key, 'boundary_ms'))
  if redis.call('HLEN', key) ~= 5
    or redis.call('HGET', key, 'schema_version') ~= '1'
    or redis.call('HGET', key, 'route') ~= route
    or owner ~= expected_owner
    or epoch ~= expected_epoch
    or boundary_ms == nil
    or next_boundary_ms == nil
    or next_boundary_ms <= boundary_ms then
    return {0, 'authority handoff precondition failed: ' .. route}
  end
end
for i = 1, n do
  local key = KEYS[i]
  local route = ARGV[3 + i]
  local boundary_ms = ARGV[3 + 2 * n + i]
  local epoch = tonumber(redis.call('HGET', key, 'epoch'))
  redis.call('HSET', key,
    'owner', new_owner,
    'epoch', tostring(epoch + 1),
    'boundary_ms', boundary_ms)
end
return {1, 'OK'}
"""


_GUARDED_XADD_SCRIPT = r"""
local key = KEYS[1]
local route = ARGV[1]
local expected_owner = ARGV[2]
local expected_epoch = ARGV[3]
local expected_boundary_ms = tonumber(ARGV[4])
local effect_cutoff_ms = tonumber(ARGV[5])
local authority_epoch = redis.call('HGET', key, 'epoch')
local authority_boundary_ms = tonumber(redis.call('HGET', key, 'boundary_ms'))
if redis.call('HLEN', key) ~= 5
  or redis.call('HGET', key, 'schema_version') ~= '1'
  or redis.call('HGET', key, 'route') ~= route then
  return {0, 'malformed authority record: ' .. route}
end
local owner = redis.call('HGET', key, 'owner')
if owner == false then
  return {0, 'missing authority record: ' .. route}
end
if owner ~= expected_owner then
  return {0, 'authority owner is ' .. owner .. ', expected ' .. expected_owner}
end
if authority_epoch ~= expected_epoch then
  return {0, 'authority epoch is ' .. tostring(authority_epoch) .. ', expected ' .. expected_epoch}
end
if authority_boundary_ms == nil or expected_boundary_ms == nil or authority_boundary_ms ~= expected_boundary_ms then
  return {0, 'authority boundary changed: ' .. route}
end
if authority_boundary_ms == nil or effect_cutoff_ms == nil or effect_cutoff_ms <= authority_boundary_ms then
  return {0, 'effect cutoff is not after authority boundary: ' .. route}
end
local stream_key = KEYS[2]
local stream_id = ARGV[6]
local maxlen = ARGV[7]
local approximate = ARGV[8]
local args = {'XADD', stream_key, 'MAXLEN'}
if approximate == '1' then
  table.insert(args, '~')
end
table.insert(args, maxlen)
table.insert(args, stream_id)
for i = 9, #ARGV, 2 do
  table.insert(args, ARGV[i])
  table.insert(args, ARGV[i + 1])
end
local returned_id = redis.call(unpack(args))
return {1, 'PUBLISHED', returned_id}
"""

_GUARDED_EXACT_XADD_SCRIPT = r"""
local function stream_id_gt(left, right)
  local left_ms, left_seq = string.match(left, '^(%d+)%-(%d+)$')
  local right_ms, right_seq = string.match(right, '^(%d+)%-(%d+)$')
  if left_ms == nil or right_ms == nil then
    return left > right
  end
  return tonumber(left_ms) > tonumber(right_ms)
    or (tonumber(left_ms) == tonumber(right_ms) and tonumber(left_seq) > tonumber(right_seq))
end
local key = KEYS[1]
local stream_key = KEYS[2]
local route = ARGV[1]
local expected_owner = ARGV[2]
local expected_epoch = ARGV[3]
local expected_boundary_ms = tonumber(ARGV[4])
local effect_cutoff_ms = tonumber(ARGV[5])
local stream_id = ARGV[6]
local maxlen = ARGV[7]
local approximate = ARGV[8]
if redis.call('HLEN', key) ~= 5
  or redis.call('HGET', key, 'schema_version') ~= '1'
  or redis.call('HGET', key, 'route') ~= route then
  return {0, 'malformed authority record: ' .. route}
end
local owner = redis.call('HGET', key, 'owner')
local authority_epoch = redis.call('HGET', key, 'epoch')
local authority_boundary_ms = tonumber(redis.call('HGET', key, 'boundary_ms'))
if owner ~= expected_owner then
  return {0, 'authority owner is ' .. tostring(owner) .. ', expected ' .. expected_owner}
end
if authority_epoch ~= expected_epoch then
  return {0, 'authority epoch is ' .. tostring(authority_epoch) .. ', expected ' .. expected_epoch}
end
if authority_boundary_ms == nil or expected_boundary_ms == nil or authority_boundary_ms ~= expected_boundary_ms then
  return {0, 'authority boundary changed: ' .. route}
end
if authority_boundary_ms == nil or effect_cutoff_ms == nil or effect_cutoff_ms <= authority_boundary_ms then
  return {0, 'effect cutoff is not after authority boundary: ' .. route}
end
local existing = redis.call('XRANGE', stream_key, stream_id, stream_id)
if #existing > 0 then
  return {1, 'EXISTING', existing[1][1], cjson.encode(existing[1][2])}
end
local head = redis.call('XREVRANGE', stream_key, '+', '-', 'COUNT', 1)
if #head > 0 and stream_id_gt(head[1][1], stream_id) then
  return {1, 'CONFLICT', head[1][1]}
end
local args = {'XADD', stream_key, 'MAXLEN'}
if approximate == '1' then
  table.insert(args, '~')
end
table.insert(args, maxlen)
table.insert(args, stream_id)
for i = 9, #ARGV, 2 do
  table.insert(args, ARGV[i])
  table.insert(args, ARGV[i + 1])
end
local returned_id = redis.call(unpack(args))
return {1, 'PUBLISHED', returned_id}
"""

_GUARDED_EXACT_LOOKUP_SCRIPT = r"""
local function stream_id_gt(left, right)
  local left_ms, left_seq = string.match(left, '^(%d+)%-(%d+)$')
  local right_ms, right_seq = string.match(right, '^(%d+)%-(%d+)$')
  if left_ms == nil or right_ms == nil then
    return left > right
  end
  return tonumber(left_ms) > tonumber(right_ms)
    or (tonumber(left_ms) == tonumber(right_ms) and tonumber(left_seq) > tonumber(right_seq))
end
local key = KEYS[1]
local stream_key = KEYS[2]
local route = ARGV[1]
local expected_owner = ARGV[2]
local expected_epoch = ARGV[3]
local expected_boundary_ms = tonumber(ARGV[4])
local effect_cutoff_ms = tonumber(ARGV[5])
local stream_id = ARGV[6]
if redis.call('HLEN', key) ~= 5
  or redis.call('HGET', key, 'schema_version') ~= '1'
  or redis.call('HGET', key, 'route') ~= route then
  return {0, 'malformed authority record: ' .. route}
end
local owner = redis.call('HGET', key, 'owner')
local authority_epoch = redis.call('HGET', key, 'epoch')
local authority_boundary_ms = tonumber(redis.call('HGET', key, 'boundary_ms'))
if owner ~= expected_owner then
  return {0, 'authority owner is ' .. tostring(owner) .. ', expected ' .. expected_owner}
end
if authority_epoch ~= expected_epoch then
  return {0, 'authority epoch is ' .. tostring(authority_epoch) .. ', expected ' .. expected_epoch}
end
if authority_boundary_ms == nil or expected_boundary_ms == nil or authority_boundary_ms ~= expected_boundary_ms then
  return {0, 'authority boundary changed: ' .. route}
end
if authority_boundary_ms == nil or effect_cutoff_ms == nil or effect_cutoff_ms <= authority_boundary_ms then
  return {0, 'effect cutoff is not after authority boundary: ' .. route}
end
local existing = redis.call('XRANGE', stream_key, stream_id, stream_id)
if #existing > 0 then
  return {1, 'EXISTING', existing[1][1], cjson.encode(existing[1][2])}
end
local head = redis.call('XREVRANGE', stream_key, '+', '-', 'COUNT', 1)
if #head > 0 and stream_id_gt(head[1][1], stream_id) then
  return {1, 'CONFLICT', head[1][1]}
end
return {1, 'ABSENT'}
"""

_ASSERT_WRITE_SCRIPT = r"""
local key = KEYS[1]
local route = ARGV[1]
local expected_owner = ARGV[2]
local expected_epoch = ARGV[3]
local expected_boundary_ms = tonumber(ARGV[4])
local effect_cutoff_ms = tonumber(ARGV[5])
if redis.call('HLEN', key) ~= 5
  or redis.call('HGET', key, 'schema_version') ~= '1'
  or redis.call('HGET', key, 'route') ~= route then
  return {0, 'malformed authority record: ' .. route}
end
if redis.call('HGET', key, 'owner') ~= expected_owner then
  return {0, 'authority owner mismatch: ' .. route}
end
if redis.call('HGET', key, 'epoch') ~= expected_epoch then
  return {0, 'authority epoch mismatch: ' .. route}
end
local boundary_ms = tonumber(redis.call('HGET', key, 'boundary_ms'))
if boundary_ms == nil or expected_boundary_ms == nil or boundary_ms ~= expected_boundary_ms then
  return {0, 'authority boundary changed: ' .. route}
end
if effect_cutoff_ms == nil or effect_cutoff_ms <= boundary_ms then
  return {0, 'effect cutoff is not after authority boundary: ' .. route}
end
return {1, 'OK'}
"""


def _decode(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


class SignalAuthorityStore:
    """Small async Valkey facade for the D11B authority contract."""

    def __init__(
        self,
        client: Any,
        *,
        managed_routes: Sequence[str] = TARGET_SIGNAL_ROUTES,
    ) -> None:
        if client is None or not callable(getattr(client, "eval", None)):
            raise TypeError("authority client must provide async eval()")
        self._client = client
        self._managed_routes = frozenset(
            normalize_signal_route(route) for route in managed_routes
        )

    @property
    def managed_routes(self) -> frozenset[str]:
        return self._managed_routes

    @property
    def client(self) -> Any:
        """Expose the one coordination client to the foreground controller."""

        return self._client

    def manages(self, route: str) -> bool:
        return normalize_signal_route(route) in self._managed_routes

    async def read(self, route: str) -> SignalRouteAuthority | None:
        normalized = normalize_signal_route(route)
        raw = await self._client.hgetall(signal_authority_key(normalized))
        if not raw:
            return None
        if not isinstance(raw, Mapping):
            raise SignalAuthorityError("authority HGETALL result must be a mapping")
        values = {_decode(key): _decode(value) for key, value in raw.items()}
        if set(values) != set(_AUTHORITY_FIELDS):
            raise SignalAuthorityError(f"malformed authority record: {normalized}")
        try:
            return SignalRouteAuthority(
                schema_version=int(values["schema_version"]),
                route=values["route"],
                owner=values["owner"],  # type: ignore[arg-type]
                epoch=int(values["epoch"]),
                boundary_ms=int(values["boundary_ms"]),
            )
        except (TypeError, ValueError) as exc:
            raise SignalAuthorityError(
                f"malformed authority record: {normalized}"
            ) from exc

    async def assert_owner(
        self, route: str, owner: SignalOwner
    ) -> SignalRouteAuthority:
        record = await self.read(route)
        if record is None:
            raise SignalAuthorityError(f"missing authority record: {route}")
        if record.owner != owner:
            raise SignalAuthorityError(
                f"authority owner for {record.route} is {record.owner}, expected {owner}"
            )
        return record

    async def assert_write(
        self,
        *,
        route: str,
        expected_owner: SignalOwner,
        expected_epoch: int,
        expected_boundary_ms: int,
        effect_cutoff_ms: int,
    ) -> SignalRouteAuthority | None:
        """Atomically validate one managed write without publishing it."""

        normalized = normalize_signal_route(route)
        if normalized not in self._managed_routes:
            return None
        _validate_owner(expected_owner, field_name="expected_owner")
        _validate_epoch(expected_epoch, field_name="expected_epoch")
        _validate_effect_cutoff(expected_boundary_ms)
        _validate_effect_cutoff(effect_cutoff_ms)
        result = await self._client.eval(
            _ASSERT_WRITE_SCRIPT,
            1,
            signal_authority_key(normalized),
            normalized,
            expected_owner,
            str(expected_epoch),
            str(expected_boundary_ms),
            str(effect_cutoff_ms),
        )
        if not result or int(result[0]) != 1:
            reason = (
                _decode(result[1]) if result and len(result) > 1 else "write denied"
            )
            raise SignalAuthorityError(reason)
        record = await self.read(normalized)
        if record is None:
            raise SignalAuthorityError(f"authority record disappeared: {normalized}")
        if record.owner != expected_owner or record.epoch != expected_epoch:
            raise SignalAuthorityError("authority changed after write validation")
        return record

    async def seed_strategy(
        self, routes: Sequence[str] = TARGET_SIGNAL_ROUTES
    ) -> tuple[SignalRouteAuthority, ...]:
        normalized = tuple(normalize_signal_route(route) for route in routes)
        if not normalized or len(set(normalized)) != len(normalized):
            raise ValueError("authority seed routes must be unique and non-empty")
        result = await self._client.eval(
            _SEED_SCRIPT,
            len(normalized),
            *(signal_authority_key(route) for route in normalized),
            len(normalized),
            *normalized,
        )
        if not result or int(result[0]) != 1:
            reason = _decode(result[1]) if result and len(result) > 1 else "seed failed"
            raise SignalAuthorityConflict(reason)
        return tuple(await self._read_many(normalized))

    async def handoff_many(
        self,
        *,
        routes: Sequence[str],
        expected_owner: SignalOwner,
        new_owner: SignalOwner,
        expected_epochs: Mapping[str, int],
        boundary_ms_by_route: Mapping[str, int],
    ) -> tuple[SignalRouteAuthority, ...]:
        normalized = tuple(normalize_signal_route(route) for route in routes)
        if not normalized or len(set(normalized)) != len(normalized):
            raise ValueError("handoff routes must be unique and non-empty")
        _validate_owner(expected_owner, field_name="expected_owner")
        _validate_owner(new_owner, field_name="new_owner")
        if expected_owner == new_owner:
            raise ValueError("handoff must change owner")
        if set(expected_epochs) != set(normalized) or set(boundary_ms_by_route) != set(
            normalized
        ):
            raise ValueError("handoff epochs/boundaries must cover exactly the routes")
        epochs: list[str] = []
        boundaries: list[str] = []
        for route in normalized:
            epoch = expected_epochs[route]
            boundary = boundary_ms_by_route[route]
            if isinstance(epoch, bool) or not isinstance(epoch, int) or epoch < 0:
                raise ValueError("expected epochs must be non-negative integers")
            if (
                isinstance(boundary, bool)
                or not isinstance(boundary, int)
                or boundary < 0
            ):
                raise ValueError("handoff boundaries must be non-negative integers")
            epochs.append(str(epoch))
            boundaries.append(str(boundary))
        result = await self._client.eval(
            _HANDOFF_SCRIPT,
            len(normalized),
            *(signal_authority_key(route) for route in normalized),
            len(normalized),
            expected_owner,
            new_owner,
            *normalized,
            *epochs,
            *boundaries,
        )
        if not result or int(result[0]) != 1:
            reason = (
                _decode(result[1]) if result and len(result) > 1 else "handoff failed"
            )
            raise SignalAuthorityConflict(reason)
        return tuple(await self._read_many(normalized))

    async def guarded_xadd(
        self,
        *,
        route: str,
        expected_owner: SignalOwner,
        expected_epoch: int | None = None,
        expected_boundary_ms: int | None = None,
        effect_cutoff_ms: int | None = None,
        stream_key: str,
        fields: Mapping[str, object],
        stream_id: str = "*",
        maxlen: int,
        approximate: bool,
    ) -> GuardedSignalWrite:
        normalized = normalize_signal_route(route)
        if normalized not in self._managed_routes:
            return GuardedSignalWrite(allowed=True, managed=False)
        _validate_owner(expected_owner, field_name="expected_owner")
        _validate_epoch(expected_epoch, field_name="expected_epoch")
        _validate_effect_cutoff(expected_boundary_ms)
        _validate_effect_cutoff(effect_cutoff_ms)
        expected_stream_key = f"signals:{normalized}"
        if stream_key != expected_stream_key:
            raise ValueError(
                "authority-managed signal stream does not match its route: "
                f"{stream_key!r} != {expected_stream_key!r}"
            )
        if isinstance(maxlen, bool) or not isinstance(maxlen, int) or maxlen <= 0:
            raise ValueError("maxlen must be a positive integer")
        if not isinstance(approximate, bool):
            raise TypeError("approximate must be bool")
        encoded: list[str] = []
        for key, value in sorted(fields.items()):
            if not isinstance(key, str) or not key:
                raise TypeError("signal field names must be non-empty strings")
            encoded.extend((key, _decode(value)))
        result = await self._client.eval(
            _GUARDED_XADD_SCRIPT,
            2,
            signal_authority_key(normalized),
            stream_key,
            normalized,
            expected_owner,
            str(expected_epoch),
            str(expected_boundary_ms),
            str(effect_cutoff_ms),
            stream_id,
            str(maxlen),
            "1" if approximate else "0",
            *encoded,
        )
        if not result:
            raise SignalAuthorityError("authority-guarded XADD returned no result")
        allowed = int(result[0]) == 1
        if not allowed:
            return GuardedSignalWrite(
                allowed=False,
                managed=True,
                reason=_decode(result[1]) if len(result) > 1 else "authority denied",
                outcome="DENIED",
            )
        return GuardedSignalWrite(
            allowed=True,
            managed=True,
            stream_id=_decode(result[2]) if len(result) > 2 else None,
            outcome="PUBLISHED",
        )

    async def guarded_exact_xadd(
        self,
        *,
        route: str,
        expected_owner: SignalOwner,
        expected_epoch: int,
        expected_boundary_ms: int,
        effect_cutoff_ms: int,
        stream_key: str,
        stream_id: str,
        fields: Mapping[str, object],
        maxlen: int,
        approximate: bool,
    ) -> GuardedSignalWrite:
        """Fence exact-ID reconciliation and XADD in one Valkey script."""

        normalized = normalize_signal_route(route)
        if normalized not in self._managed_routes:
            return GuardedSignalWrite(allowed=True, managed=False)
        self._validate_stream_arguments(
            normalized=normalized,
            stream_key=stream_key,
            stream_id=stream_id,
            maxlen=maxlen,
            approximate=approximate,
        )
        _validate_owner(expected_owner, field_name="expected_owner")
        _validate_epoch(expected_epoch, field_name="expected_epoch")
        _validate_effect_cutoff(expected_boundary_ms)
        _validate_effect_cutoff(effect_cutoff_ms)
        encoded = self._encode_fields(fields)
        result = await self._client.eval(
            _GUARDED_EXACT_XADD_SCRIPT,
            2,
            signal_authority_key(normalized),
            stream_key,
            normalized,
            expected_owner,
            str(expected_epoch),
            str(expected_boundary_ms),
            str(effect_cutoff_ms),
            stream_id,
            str(maxlen),
            "1" if approximate else "0",
            *encoded,
        )
        return self._decode_guarded_result(result)

    async def guarded_exact_lookup(
        self,
        *,
        route: str,
        expected_owner: SignalOwner,
        expected_epoch: int,
        expected_boundary_ms: int,
        effect_cutoff_ms: int,
        stream_key: str,
        stream_id: str,
    ) -> GuardedSignalWrite:
        """Reconcile an ambiguous exact-ID write under the same fence."""

        normalized = normalize_signal_route(route)
        if normalized not in self._managed_routes:
            return GuardedSignalWrite(allowed=True, managed=False)
        self._validate_stream_arguments(
            normalized=normalized,
            stream_key=stream_key,
            stream_id=stream_id,
            maxlen=1,
            approximate=False,
        )
        _validate_owner(expected_owner, field_name="expected_owner")
        _validate_epoch(expected_epoch, field_name="expected_epoch")
        _validate_effect_cutoff(expected_boundary_ms)
        _validate_effect_cutoff(effect_cutoff_ms)
        result = await self._client.eval(
            _GUARDED_EXACT_LOOKUP_SCRIPT,
            2,
            signal_authority_key(normalized),
            stream_key,
            normalized,
            expected_owner,
            str(expected_epoch),
            str(expected_boundary_ms),
            str(effect_cutoff_ms),
            stream_id,
        )
        return self._decode_guarded_result(result)

    @staticmethod
    def _validate_stream_arguments(
        *,
        normalized: str,
        stream_key: str,
        stream_id: str,
        maxlen: int,
        approximate: bool,
    ) -> None:
        expected_stream_key = f"signals:{normalized}"
        if stream_key != expected_stream_key:
            raise ValueError(
                "authority-managed signal stream does not match its route: "
                f"{stream_key!r} != {expected_stream_key!r}"
            )
        if not isinstance(stream_id, str) or not stream_id:
            raise TypeError("stream_id must be non-empty text")
        if isinstance(maxlen, bool) or not isinstance(maxlen, int) or maxlen <= 0:
            raise ValueError("maxlen must be a positive integer")
        if not isinstance(approximate, bool):
            raise TypeError("approximate must be bool")

    @staticmethod
    def _encode_fields(fields: Mapping[str, object]) -> list[str]:
        encoded: list[str] = []
        for key, value in sorted(fields.items()):
            if not isinstance(key, str) or not key:
                raise TypeError("signal field names must be non-empty strings")
            encoded.extend((key, _decode(value)))
        return encoded

    @staticmethod
    def _decode_guarded_result(result: object) -> GuardedSignalWrite:
        if not result or not isinstance(result, Sequence):
            raise SignalAuthorityError("authority-guarded XADD returned no result")
        if int(result[0]) == 0:
            return GuardedSignalWrite(
                allowed=False,
                managed=True,
                reason=_decode(result[1]) if len(result) > 1 else "authority denied",
                outcome="DENIED",
            )
        outcome = _decode(result[1]) if len(result) > 1 else "PUBLISHED"
        if outcome == "PUBLISHED":
            return GuardedSignalWrite(
                allowed=True,
                managed=True,
                stream_id=_decode(result[2]) if len(result) > 2 else None,
                outcome="PUBLISHED",
            )
        if outcome == "EXISTING":
            existing_fields: dict[str, str] = {}
            if len(result) > 3:
                import json

                raw_fields = json.loads(_decode(result[3]))
                if not isinstance(raw_fields, list) or len(raw_fields) % 2:
                    raise SignalAuthorityError("existing signal fields are malformed")
                existing_fields = {
                    str(raw_fields[index]): str(raw_fields[index + 1])
                    for index in range(0, len(raw_fields), 2)
                }
            return GuardedSignalWrite(
                allowed=True,
                managed=True,
                stream_id=_decode(result[2]) if len(result) > 2 else None,
                outcome="EXISTING",
                existing_fields=existing_fields,
            )
        if outcome == "CONFLICT":
            return GuardedSignalWrite(
                allowed=True,
                managed=True,
                stream_id=_decode(result[2]) if len(result) > 2 else None,
                reason="stream head advanced past required explicit ID",
                outcome="CONFLICT",
            )
        raise SignalAuthorityError(f"unsupported guarded result: {outcome}")

    async def _read_many(self, routes: Sequence[str]) -> list[SignalRouteAuthority]:
        values: list[SignalRouteAuthority] = []
        for route in routes:
            record = await self.read(route)
            if record is None:
                raise SignalAuthorityError(f"authority record disappeared: {route}")
            values.append(record)
        return values


def _validate_epoch(value: object, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return value


def _validate_effect_cutoff(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("effect_cutoff_ms must be a non-negative integer")
    return value


__all__ = [
    "TARGET_SIGNAL_ROUTES",
    "GuardedSignalWrite",
    "SignalAuthorityConflict",
    "SignalAuthorityError",
    "SignalAuthorityStore",
    "SignalOwner",
    "SignalRouteAuthority",
    "normalize_signal_route",
    "signal_authority_key",
    "signal_route_from_stream",
]
