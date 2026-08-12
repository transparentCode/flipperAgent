"""In-memory control and replacement boundary for the ingestion runtime."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from apps.ingestion_app.domain.recovery import RecoveryRequest
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


class RuntimeController:
    """Own validated settings and the task for the current supervisor instance."""

    def __init__(
        self,
        *,
        settings: IngestionSettings,
        supervisor_factory: Callable[[IngestionSettings], RuntimeSupervisor],
    ) -> None:
        if not isinstance(settings, IngestionSettings):
            raise TypeError("settings must be IngestionSettings")
        if not callable(supervisor_factory):
            raise TypeError("supervisor_factory must be callable")

        self._settings = settings
        self._supervisor_factory = supervisor_factory
        self._supervisor: RuntimeSupervisor | None = None
        self._supervisor_task: asyncio.Task[None] | None = None
        self._desired_state = DesiredRuntimeState.RUNNING
        self._last_error: str | None = None
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
        if self._supervisor is None:
            state = RuntimeState.ERROR if self._last_error else RuntimeState.STOPPED
            return RuntimeSnapshot(
                desired_state=self._desired_state,
                state=state,
                last_error=self._last_error,
            )

        supervisor_snapshot = self._supervisor.snapshot()
        return RuntimeSnapshot(
            desired_state=self._desired_state,
            state=supervisor_snapshot.state,
            last_error=supervisor_snapshot.last_error or self._last_error,
        )

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

    def _consume_supervisor_task(self, task: asyncio.Task[None]) -> None:
        if task is not self._supervisor_task or task.cancelled():
            return
        try:
            task.result()
        except asyncio.CancelledError:
            return
        except Exception as exc:  # noqa: BLE001
            self._last_error = str(exc)

    def _start_supervisor(self, supervisor: RuntimeSupervisor) -> None:
        if self._supervisor_task is not None and not self._supervisor_task.done():
            return
        task = asyncio.create_task(supervisor.run(), name="ingestion-supervisor")
        self._supervisor_task = task
        task.add_done_callback(self._consume_supervisor_task)

    async def _stop_current_supervisor(self) -> None:
        supervisor = self._supervisor
        task = self._supervisor_task
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
        except Exception as exc:  # noqa: BLE001
            self._last_error = str(exc)
        finally:
            self._supervisor_task = None

    def _install_supervisor(self, supervisor: RuntimeSupervisor | None) -> None:
        self._supervisor = supervisor
        if supervisor is None:
            return
        if self._desired_state is DesiredRuntimeState.PAUSED:
            supervisor.pause()
        elif self._started:
            self._start_supervisor(supervisor)

    async def _restore_runtime_state(
        self,
        *,
        settings: IngestionSettings,
        desired_state: DesiredRuntimeState,
        started: bool,
        last_error: str | None,
    ) -> None:
        """Restore a fresh runtime after a cancelled control operation."""
        self._settings = settings
        self._desired_state = desired_state
        self._last_error = last_error
        self._supervisor = None
        self._supervisor_task = None
        self._started = started
        if started:
            self._install_supervisor(self._build_supervisor(settings))

    async def start(self) -> None:
        async with self._operation_lock:
            if self._started:
                return
            supervisor = self._build_supervisor(self._settings)
            self._last_error = None
            self._started = True
            try:
                self._install_supervisor(supervisor)
            except BaseException:
                self._started = False
                self._supervisor = None
                self._supervisor_task = None
                raise

    async def close(self) -> None:
        async with self._operation_lock:
            try:
                await self._stop_current_supervisor()
            finally:
                self._supervisor = None
                self._started = False

    async def pause(self) -> RuntimeSnapshot:
        async with self._operation_lock:
            if not self._started:
                raise RuntimeControlConflictError("controller is not started")
            self._desired_state = DesiredRuntimeState.PAUSED
            if self._supervisor is not None:
                self._supervisor.pause()
            return self.snapshot()

    async def resume(self) -> RuntimeSnapshot:
        async with self._operation_lock:
            if not self._started:
                raise RuntimeControlConflictError("controller is not started")
            self._desired_state = DesiredRuntimeState.RUNNING
            self._last_error = None
            if self._supervisor is None:
                self._install_supervisor(self._build_supervisor(self._settings))
            elif self._supervisor_task is None or self._supervisor_task.done():
                if self._supervisor.snapshot().state is RuntimeState.ERROR:
                    raise RuntimeControlConflictError(
                        "runtime is in ERROR; reconnect is required"
                    )
                self._supervisor.resume()
                self._start_supervisor(self._supervisor)
            else:
                self._supervisor.resume()
            return self.snapshot()

    async def reconnect(self) -> RuntimeSnapshot:
        async with self._operation_lock:
            if not self._started:
                raise RuntimeControlConflictError("controller is not started")
            if self._desired_state is DesiredRuntimeState.PAUSED:
                raise RuntimeControlConflictError("cannot reconnect a paused runtime")
            replacement = self._build_supervisor(self._settings)
            if replacement is None:
                raise RuntimeControlConflictError(
                    "cannot reconnect with no enabled runtime assets"
                )
            await self._stop_current_supervisor()
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
            old_settings = self._settings
            old_desired_state = self._desired_state
            old_last_error = self._last_error
            was_started = self._started
            replacement = self._build_supervisor(settings)

            if not was_started:
                self._settings = settings
                self._supervisor = None
                self._supervisor_task = None
                self._last_error = None
                return self.snapshot()

            try:
                await self._stop_current_supervisor()
                self._settings = settings
                self._supervisor = None
                self._supervisor_task = None
                self._last_error = None
                self._install_supervisor(replacement)
                return self.snapshot()
            except asyncio.CancelledError:
                try:
                    await self._restore_runtime_state(
                        settings=old_settings,
                        desired_state=old_desired_state,
                        started=was_started,
                        last_error=old_last_error,
                    )
                except BaseException as restore_exc:
                    raise RuntimeError(
                        "cancelled settings replacement could not restore runtime"
                    ) from restore_exc
                raise

    async def recover(self, request: RecoveryRequest) -> RuntimeSnapshot:
        if not isinstance(request, RecoveryRequest):
            raise TypeError("request must be a RecoveryRequest")

        async with self._operation_lock:
            if not self._started:
                raise RuntimeControlConflictError("controller is not started")
            if not _has_enabled_assets(self._settings):
                raise RuntimeControlConflictError(
                    "cannot recover with no enabled runtime assets"
                )
            desired_state = self._desired_state
            old_settings = self._settings
            old_last_error = self._last_error
            was_started = self._started

            try:
                await self._stop_current_supervisor()
                self._supervisor = None
                self._supervisor_task = None
                offline_supervisor = self._build_supervisor(self._settings)
                if offline_supervisor is None:  # pragma: no cover
                    raise RuntimeControlConflictError(
                        "cannot recover with no enabled runtime assets"
                    )
                await offline_supervisor.execute_recovery(request)
                replacement = self._build_supervisor(self._settings)
                self._supervisor = None
                self._install_supervisor(replacement)
                self._desired_state = desired_state
                self._last_error = None
                return self.snapshot()
            except asyncio.CancelledError:
                try:
                    await self._restore_runtime_state(
                        settings=old_settings,
                        desired_state=desired_state,
                        started=was_started,
                        last_error=old_last_error,
                    )
                except BaseException as restore_exc:
                    raise RuntimeError(
                        "cancelled recovery could not restore runtime"
                    ) from restore_exc
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
