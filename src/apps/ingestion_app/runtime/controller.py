"""In-memory control and replacement boundary for the ingestion runtime."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass

from apps.ingestion_app.domain.recovery import RecoveryRequest
from apps.ingestion_app.observability import IngestionObservability
from apps.ingestion_app.providers.base import TransportDeadlineExceeded
from apps.ingestion_app.runtime.supervisor import (
    DesiredRuntimeState,
    RuntimeSnapshot,
    RuntimeState,
    RuntimeSupervisor,
)
from apps.ingestion_app.settings import IngestionSettings


class RuntimeControlConflictError(RuntimeError):
    """A requested control operation conflicts with the desired runtime state."""


def _has_enabled_assets(settings: IngestionSettings) -> bool:
    return any(asset.enabled for asset in settings.assets.values())


@dataclass(frozen=True, slots=True)
class _RuntimeCheckpoint:
    """Controller state needed to restore a cancelled generation transition."""

    settings: IngestionSettings
    desired_state: DesiredRuntimeState
    started: bool
    last_error: str | None


class RuntimeController:
    """Own validated settings and the task for the current supervisor instance."""

    def __init__(
        self,
        *,
        settings: IngestionSettings,
        supervisor_factory: Callable[[IngestionSettings], RuntimeSupervisor],
        observability: IngestionObservability | None = None,
    ) -> None:
        if not isinstance(settings, IngestionSettings):
            raise TypeError("settings must be IngestionSettings")
        if not callable(supervisor_factory):
            raise TypeError("supervisor_factory must be callable")
        if observability is not None and not isinstance(
            observability, IngestionObservability
        ):
            raise TypeError("observability must be IngestionObservability")

        self._settings = settings
        self._supervisor_factory = supervisor_factory
        self._supervisor: RuntimeSupervisor | None = None
        self._status_supervisor: RuntimeSupervisor | None = None
        self._supervisor_task: asyncio.Task[None] | None = None
        self._observability = observability
        self._desired_state = DesiredRuntimeState.RUNNING
        self._last_error: str | None = None
        self._fatal_error: str | None = None
        self._started = False
        self._operation_lock = asyncio.Lock()

    @property
    def settings(self) -> IngestionSettings:
        """Return the current last-known-good semantic settings snapshot."""
        return self._settings

    @property
    def enabled_asset_count(self) -> int:
        return sum(1 for asset in self._settings.assets.values() if asset.enabled)

    @property
    def is_started(self) -> bool:
        """Return whether this controller owns initialized runtime control."""
        return self._started

    def snapshot(self) -> RuntimeSnapshot:
        """Return an immutable status snapshot without performing I/O."""
        self._sync_supervisor_quarantine()
        supervisor = self._supervisor or self._status_supervisor
        if supervisor is None:
            state = RuntimeState.ERROR if self._last_error else RuntimeState.STOPPED
            return RuntimeSnapshot(
                desired_state=self._desired_state,
                state=state,
                last_error=self._last_error,
            )

        supervisor_snapshot = supervisor.snapshot()
        if supervisor_snapshot.last_error is not None:
            self._last_error = supervisor_snapshot.last_error
        state = supervisor_snapshot.state
        if self._last_error is not None or self._fatal_error is not None:
            state = RuntimeState.ERROR
        return RuntimeSnapshot(
            desired_state=self._desired_state,
            state=state,
            last_error=supervisor_snapshot.last_error or self._last_error,
        )

    def _sync_supervisor_quarantine(self) -> None:
        supervisor = self._supervisor or self._status_supervisor
        if supervisor is None or not bool(getattr(supervisor, "quarantined", False)):
            return
        supervisor_snapshot = supervisor.snapshot()
        self._latch_fatal(
            RuntimeError(
                supervisor_snapshot.last_error
                or "ingestion transport lifecycle is quarantined"
            )
        )

    @property
    def quarantined(self) -> bool:
        return self._fatal_error is not None

    def _latch_fatal(self, error: BaseException) -> None:
        self._fatal_error = str(error)
        self._last_error = self._fatal_error
        if self._observability is not None:
            self._observability.set_runtime_live(False)

    def validate_settings(self, settings: IngestionSettings) -> None:
        """Validate settings against the injected runtime composition only."""
        if not isinstance(settings, IngestionSettings):
            raise TypeError("settings must be IngestionSettings")
        if _has_enabled_assets(settings):
            supervisor = self._build_supervisor(settings)
            if supervisor is None:  # pragma: no cover - defensive composition check
                raise TypeError("supervisor_factory returned no supervisor")

    def _build_supervisor(
        self,
        settings: IngestionSettings,
    ) -> RuntimeSupervisor | None:
        if not _has_enabled_assets(settings):
            return None
        supervisor = self._supervisor_factory(settings)
        if supervisor is None:
            raise TypeError("supervisor_factory returned no supervisor")
        required = ("run", "stop", "snapshot", "execute_recovery")
        if any(not callable(getattr(supervisor, name, None)) for name in required):
            raise TypeError("supervisor_factory returned an incompatible supervisor")
        return supervisor

    def _checkpoint(self) -> _RuntimeCheckpoint:
        return _RuntimeCheckpoint(
            settings=self._settings,
            desired_state=self._desired_state,
            started=self._started,
            last_error=self._last_error,
        )

    def _consume_supervisor_task(self, task: asyncio.Task[None]) -> None:
        if task is not self._supervisor_task:
            self._sync_supervisor_quarantine()
            return
        if task.cancelled():
            self._sync_supervisor_quarantine()
            return
        try:
            task.result()
        except asyncio.CancelledError:
            return
        except TransportDeadlineExceeded as exc:
            self._latch_fatal(exc)
        except Exception as exc:  # noqa: BLE001
            self._last_error = str(exc)
            self._sync_supervisor_quarantine()
        else:
            self._sync_supervisor_quarantine()

    def _start_supervisor(self, supervisor: RuntimeSupervisor) -> None:
        if self._supervisor_task is not None and not self._supervisor_task.done():
            return
        task = asyncio.create_task(supervisor.run(), name="ingestion-supervisor")
        self._supervisor_task = task
        task.add_done_callback(self._consume_supervisor_task)

    async def _stop_current_supervisor(self) -> None:
        supervisor = self._supervisor
        task = self._supervisor_task
        self._sync_supervisor_quarantine()
        try:
            if supervisor is not None:
                supervisor.stop()
            if task is not None:
                await task
        except asyncio.CancelledError:
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            raise
        except TransportDeadlineExceeded as exc:
            self._latch_fatal(exc)
            raise
        except Exception as exc:  # noqa: BLE001
            self._last_error = str(exc)
        finally:
            self._sync_supervisor_quarantine()
            self._supervisor_task = None

    async def _stop_for_transition(self, operation: str) -> None:
        """Stop the current generation before detaching it for a transition."""
        await self._stop_current_supervisor()
        self._sync_supervisor_quarantine()
        if self._fatal_error is not None:
            raise RuntimeControlConflictError(
                f"runtime is quarantined; {operation} is not permitted"
            )
        self._supervisor = None
        self._supervisor_task = None

    def _install_supervisor(self, supervisor: RuntimeSupervisor | None) -> None:
        self._supervisor = supervisor
        if supervisor is not None:
            self._status_supervisor = supervisor
        if self._observability is not None:
            self._observability.install_active_lanes(
                () if supervisor is None else supervisor.active_lanes
            )
        if supervisor is None:
            return
        if self._desired_state is DesiredRuntimeState.PAUSED:
            supervisor.pause()
        elif self._started:
            self._start_supervisor(supervisor)

    def _restore_runtime_state(self, checkpoint: _RuntimeCheckpoint) -> None:
        """Restore a fresh runtime after a cancelled control operation."""
        self._settings = checkpoint.settings
        self._desired_state = checkpoint.desired_state
        self._last_error = self._fatal_error or checkpoint.last_error
        self._supervisor = None
        self._supervisor_task = None
        self._started = checkpoint.started
        if checkpoint.started and self._fatal_error is None:
            self._install_supervisor(self._build_supervisor(checkpoint.settings))

    async def start(self) -> None:
        async with self._operation_lock:
            self._sync_supervisor_quarantine()
            if self._fatal_error is not None:
                raise RuntimeControlConflictError(
                    "runtime is quarantined; operator restart is required"
                )
            if self._started:
                return
            supervisor = self._build_supervisor(self._settings)
            self._last_error = None
            self._started = True
            try:
                self._install_supervisor(supervisor)
            except BaseException:
                self._started = False
                self._install_supervisor(None)
                self._supervisor_task = None
                raise

    async def close(self) -> None:
        async with self._operation_lock:
            self._sync_supervisor_quarantine()
            try:
                await self._stop_current_supervisor()
            finally:
                self._sync_supervisor_quarantine()
                self._install_supervisor(None)
                self._status_supervisor = None
                self._started = False

    async def pause(self) -> RuntimeSnapshot:
        async with self._operation_lock:
            self._sync_supervisor_quarantine()
            if not self._started:
                raise RuntimeControlConflictError("controller is not started")
            self._desired_state = DesiredRuntimeState.PAUSED
            if self._supervisor is not None:
                self._supervisor.pause()
            return self.snapshot()

    async def resume(self) -> RuntimeSnapshot:
        async with self._operation_lock:
            self._sync_supervisor_quarantine()
            if not self._started:
                raise RuntimeControlConflictError("controller is not started")
            if self._fatal_error is not None:
                raise RuntimeControlConflictError(
                    "runtime is quarantined; reconnect is not permitted"
                )
            self._desired_state = DesiredRuntimeState.RUNNING
            if self._supervisor is None:
                self._install_supervisor(self._build_supervisor(self._settings))
            elif self._supervisor_task is None or self._supervisor_task.done():
                if self._supervisor.snapshot().state is RuntimeState.ERROR:
                    raise RuntimeControlConflictError(
                        "runtime is in ERROR; reconnect is required"
                    )
                self._last_error = None
                self._supervisor.resume()
                self._start_supervisor(self._supervisor)
            else:
                self._last_error = None
                self._supervisor.resume()
            return self.snapshot()

    async def reconnect(self) -> RuntimeSnapshot:
        async with self._operation_lock:
            self._sync_supervisor_quarantine()
            if not self._started:
                raise RuntimeControlConflictError("controller is not started")
            if self._fatal_error is not None:
                raise RuntimeControlConflictError(
                    "runtime is quarantined; reconnect is not permitted"
                )
            if self._desired_state is DesiredRuntimeState.PAUSED:
                raise RuntimeControlConflictError("cannot reconnect a paused runtime")
            replacement = self._build_supervisor(self._settings)
            if replacement is None:
                raise RuntimeControlConflictError(
                    "cannot reconnect with no enabled runtime assets"
                )
            await self._stop_for_transition("reconnect")
            self._install_supervisor(replacement)
            self._last_error = None
            return self.snapshot()

    async def replace_settings(
        self,
        settings: IngestionSettings,
    ) -> RuntimeSnapshot:
        if not isinstance(settings, IngestionSettings):
            raise TypeError("settings must be IngestionSettings")
        async with self._operation_lock:
            self._sync_supervisor_quarantine()
            if self._fatal_error is not None:
                raise RuntimeControlConflictError(
                    "runtime is quarantined; settings replacement is not permitted"
                )
            checkpoint = self._checkpoint()
            replacement = self._build_supervisor(settings)

            if not checkpoint.started:
                self._settings = settings
                self._supervisor = None
                self._supervisor_task = None
                self._last_error = None
                return self.snapshot()

            try:
                await self._stop_for_transition("settings replacement")
                self._settings = settings
                self._last_error = None
                self._install_supervisor(replacement)
                return self.snapshot()
            except asyncio.CancelledError:
                try:
                    self._restore_runtime_state(checkpoint)
                except BaseException as restore_exc:
                    raise RuntimeError(
                        "cancelled settings replacement could not restore runtime"
                    ) from restore_exc
                raise

    async def recover(self, request: RecoveryRequest) -> RuntimeSnapshot:
        if not isinstance(request, RecoveryRequest):
            raise TypeError("request must be a RecoveryRequest")

        async with self._operation_lock:
            self._sync_supervisor_quarantine()
            if not self._started:
                raise RuntimeControlConflictError("controller is not started")
            if self._fatal_error is not None:
                raise RuntimeControlConflictError(
                    "runtime is quarantined; recovery is not permitted"
                )
            if not _has_enabled_assets(self._settings):
                raise RuntimeControlConflictError(
                    "cannot recover with no enabled runtime assets"
                )
            checkpoint = self._checkpoint()

            try:
                await self._stop_for_transition("recovery")
                offline_supervisor = self._build_supervisor(self._settings)
                if offline_supervisor is None:  # pragma: no cover
                    raise RuntimeControlConflictError(
                        "cannot recover with no enabled runtime assets"
                    )
                await offline_supervisor.execute_recovery(request)
                replacement = self._build_supervisor(self._settings)
                self._supervisor = None
                self._install_supervisor(replacement)
                self._desired_state = checkpoint.desired_state
                self._last_error = None
                return self.snapshot()
            except asyncio.CancelledError:
                try:
                    self._restore_runtime_state(checkpoint)
                except BaseException as restore_exc:
                    raise RuntimeError(
                        "cancelled recovery could not restore runtime"
                    ) from restore_exc
                raise
            except TransportDeadlineExceeded as exc:
                self._latch_fatal(exc)
                self._supervisor = None
                self._supervisor_task = None
                raise
            except Exception as exc:
                self._supervisor = None
                self._supervisor_task = None
                self._last_error = str(exc)
                raise


__all__ = [
    "RuntimeControlConflictError",
    "RuntimeController",
]
