"""In-memory control and replacement boundary for the ingestion runtime."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from apps.ingestion_app.domain.recovery import RecoveryRequest
from apps.ingestion_app.observability import IngestionObservability
from apps.ingestion_app.planning import IngestionPlan
from apps.ingestion_app.providers.base import TransportDeadlineExceeded
from apps.ingestion_app.runtime.state import (
    DesiredRuntimeState,
    RuntimeSnapshot,
    RuntimeState,
)
from apps.ingestion_app.runtime.supervisor import (
    RuntimeSupervisor,
)
from apps.ingestion_app.settings import IngestionSettings

_LOGGER = logging.getLogger(__name__)


class RuntimeControlConflictError(RuntimeError):
    """A requested control operation conflicts with the desired runtime state."""


def _has_enabled_assets(settings: IngestionSettings) -> bool:
    return any(asset.enabled for asset in settings.assets.values())


async def _noop_historical_provider_quiescence() -> None:
    return None


@dataclass(frozen=True, slots=True)
class _RuntimeCheckpoint:
    """Controller state needed to restore a cancelled generation transition."""

    settings: IngestionSettings
    plan: IngestionPlan
    desired_state: DesiredRuntimeState
    started: bool
    last_error: str | None


class RuntimeController:
    """Own validated settings and the task for the current supervisor instance."""

    def __init__(
        self,
        *,
        settings: IngestionSettings,
        plan_factory: Callable[[IngestionSettings], IngestionPlan],
        supervisor_factory: Callable[[IngestionPlan], RuntimeSupervisor],
        observability: IngestionObservability | None = None,
        historical_provider_quiescence: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        if not isinstance(settings, IngestionSettings):
            raise TypeError("settings must be IngestionSettings")
        if not callable(plan_factory):
            raise TypeError("plan_factory must be callable")
        if not callable(supervisor_factory):
            raise TypeError("supervisor_factory must be callable")
        if observability is not None and not isinstance(
            observability, IngestionObservability
        ):
            raise TypeError("observability must be IngestionObservability")
        if historical_provider_quiescence is not None and not callable(
            historical_provider_quiescence
        ):
            raise TypeError("historical_provider_quiescence must be callable")

        self._plan_factory = plan_factory
        self._supervisor_factory = supervisor_factory
        self._settings = settings
        self._plan = self._compile_plan(settings)
        self._supervisor: RuntimeSupervisor | None = None
        self._status_supervisor: RuntimeSupervisor | None = None
        self._supervisor_task: asyncio.Task[None] | None = None
        self._observability = observability
        self._historical_provider_quiescence = (
            historical_provider_quiescence or _noop_historical_provider_quiescence
        )
        self._desired_state = DesiredRuntimeState.RUNNING
        self._last_error: str | None = None
        self._terminal_error: str | None = None
        self._fatal_error: str | None = None
        self._started = False
        self._operation_lock = asyncio.Lock()

    @property
    def settings(self) -> IngestionSettings:
        """Return the current last-known-good semantic settings snapshot."""
        return self._settings

    @property
    def plan(self) -> IngestionPlan:
        """Return the current last-known-good immutable runtime plan."""
        return self._plan

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
        if self._supervisor is None:
            error = self._fatal_error or self._terminal_error or self._last_error
            state = RuntimeState.ERROR if error else RuntimeState.STOPPED
            return RuntimeSnapshot(
                desired_state=self._desired_state,
                state=state,
                last_error=error,
            )

        supervisor_snapshot = self._supervisor.snapshot()
        if (
            supervisor_snapshot.state is RuntimeState.LIVE
            and self._fatal_error is None
            and self._terminal_error is None
        ):
            self._last_error = None
            return RuntimeSnapshot(
                desired_state=self._desired_state,
                state=RuntimeState.LIVE,
                last_error=None,
            )
        if supervisor_snapshot.last_error is not None:
            self._last_error = supervisor_snapshot.last_error
        state = supervisor_snapshot.state
        if self._terminal_error is not None or self._fatal_error is not None:
            state = RuntimeState.ERROR
        error = (
            self._fatal_error
            or self._terminal_error
            or supervisor_snapshot.last_error
            or self._last_error
        )
        return RuntimeSnapshot(
            desired_state=self._desired_state,
            state=state,
            last_error=error,
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

    def _latch_terminal_transition_failure(self, error: BaseException) -> None:
        """Fail closed after a generation was detached unsuccessfully."""
        if self._fatal_error is not None:
            return
        self._terminal_error = str(error)
        self._last_error = self._terminal_error
        self._supervisor = None
        self._supervisor_task = None
        if self._observability is not None:
            self._observability.set_runtime_live(False)
            try:
                self._observability.install_active_lanes(())
            except Exception as exc:
                _LOGGER.debug(
                    "failed to clear active-lane observability after transition failure",
                    exc_info=exc,
                )

    def validate_settings(self, settings: IngestionSettings) -> None:
        """Validate settings against the injected runtime composition only."""
        self._compile_plan(settings)

    def _compile_plan(self, settings: IngestionSettings) -> IngestionPlan:
        if not isinstance(settings, IngestionSettings):
            raise TypeError("settings must be IngestionSettings")
        plan = self._plan_factory(settings)
        if not isinstance(plan, IngestionPlan):
            raise TypeError("plan_factory returned an invalid ingestion plan")
        return plan

    def _build_supervisor(
        self,
        plan: IngestionPlan,
    ) -> RuntimeSupervisor | None:
        if not plan.lanes:
            return None
        supervisor = self._supervisor_factory(plan)
        if supervisor is None:
            raise TypeError("supervisor_factory returned no supervisor")
        required = ("run", "stop", "snapshot", "execute_recovery")
        if any(not callable(getattr(supervisor, name, None)) for name in required):
            raise TypeError("supervisor_factory returned an incompatible supervisor")
        return supervisor

    def _checkpoint(self) -> _RuntimeCheckpoint:
        return _RuntimeCheckpoint(
            settings=self._settings,
            plan=self._plan,
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
            self._latch_terminal_transition_failure(exc)
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
            self._supervisor_task = None

    async def _stop_for_transition(self, operation: str) -> None:
        """Stop the current generation before detaching it for a transition."""
        await self._stop_current_supervisor()
        try:
            await self._wait_for_historical_provider_quiescence()
        except TransportDeadlineExceeded:
            raise
        except Exception as exc:
            self._latch_terminal_transition_failure(exc)
            raise
        self._sync_supervisor_quarantine()
        if self._fatal_error is not None:
            raise RuntimeControlConflictError(
                f"runtime is quarantined; {operation} is not permitted"
            )
        self._supervisor = None
        self._supervisor_task = None

    def _install_supervisor(
        self,
        supervisor: RuntimeSupervisor | None,
        *,
        accept_supervisorless: bool = False,
    ) -> None:
        if self._desired_state is DesiredRuntimeState.PAUSED:
            supervisor = None
        if self._observability is not None:
            self._observability.install_active_lanes(
                () if supervisor is None else supervisor.active_lanes
            )
        if supervisor is None:
            self._supervisor = None
            if accept_supervisorless and self._fatal_error is None:
                self._terminal_error = None
                self._last_error = None
            return
        if self._started:
            self._start_supervisor(supervisor)
        self._supervisor = supervisor
        self._status_supervisor = supervisor
        self._terminal_error = None

    async def _wait_for_historical_provider_quiescence(self) -> None:
        try:
            await self._historical_provider_quiescence()
        except TransportDeadlineExceeded as exc:
            self._latch_fatal(exc)
            raise

    async def _wait_for_quiescence_during_restore(self) -> None:
        """Finish the rollback fence even if cancellation is delivered again."""
        task = asyncio.create_task(
            self._wait_for_historical_provider_quiescence(),
            name="ingestion-controller-rollback-quiescence",
        )
        while True:
            try:
                await asyncio.shield(task)
                return
            except asyncio.CancelledError:
                if task.cancelled():
                    raise

    async def _restore_runtime_state(self, checkpoint: _RuntimeCheckpoint) -> None:
        """Restore a fresh runtime after a cancelled control operation."""
        self._desired_state = checkpoint.desired_state
        self._last_error = self._fatal_error or checkpoint.last_error
        self._supervisor = None
        self._supervisor_task = None
        self._started = checkpoint.started
        try:
            if checkpoint.started and self._fatal_error is None:
                await self._wait_for_quiescence_during_restore()
                self._sync_supervisor_quarantine()
            if checkpoint.started and self._fatal_error is None:
                self._settings = checkpoint.settings
                self._plan = checkpoint.plan
                if checkpoint.desired_state is DesiredRuntimeState.RUNNING:
                    restored = self._build_supervisor(checkpoint.plan)
                    self._install_supervisor(
                        restored,
                        accept_supervisorless=restored is None,
                    )
                else:
                    self._install_supervisor(None, accept_supervisorless=True)
            elif not checkpoint.started:
                self._settings = checkpoint.settings
                self._plan = checkpoint.plan
                self._install_supervisor(None, accept_supervisorless=True)
        except TransportDeadlineExceeded as exc:
            self._latch_fatal(exc)
            self._supervisor = None
            self._supervisor_task = None
            raise
        except Exception as exc:
            self._latch_terminal_transition_failure(exc)
            raise

    async def start(self) -> None:
        async with self._operation_lock:
            self._sync_supervisor_quarantine()
            if self._fatal_error is not None:
                raise RuntimeControlConflictError(
                    "runtime is quarantined; operator restart is required"
                )
            if self._started:
                return
            supervisor = (
                self._build_supervisor(self._plan)
                if self._desired_state is DesiredRuntimeState.RUNNING
                else None
            )
            self._last_error = None
            self._started = True
            try:
                self._install_supervisor(
                    supervisor,
                    accept_supervisorless=supervisor is None,
                )
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
                self._supervisor.stop()
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
            if self._terminal_error is not None:
                raise RuntimeControlConflictError(
                    "runtime is in ERROR; reconnect is required"
                )
            if self._desired_state is DesiredRuntimeState.PAUSED:
                if (
                    self._supervisor is not None
                    and self._supervisor.snapshot().state is RuntimeState.ERROR
                    and (self._supervisor_task is None or self._supervisor_task.done())
                ):
                    raise RuntimeControlConflictError(
                        "runtime is in ERROR; reconnect is required"
                    )
                await self._stop_for_transition("resume")
                self._desired_state = DesiredRuntimeState.RUNNING
                try:
                    replacement = self._build_supervisor(self._plan)
                    self._install_supervisor(
                        replacement,
                        accept_supervisorless=replacement is None,
                    )
                except TransportDeadlineExceeded as exc:
                    self._latch_fatal(exc)
                    raise
                except Exception as exc:
                    self._latch_terminal_transition_failure(exc)
                    raise
                self._last_error = None
            elif self._supervisor is None:
                self._last_error = None
            elif self._supervisor_task is None or self._supervisor_task.done():
                if self._supervisor.snapshot().state is RuntimeState.ERROR:
                    raise RuntimeControlConflictError(
                        "runtime is in ERROR; reconnect is required"
                    )
                await self._stop_for_transition("resume")
                try:
                    replacement = self._build_supervisor(self._plan)
                    self._install_supervisor(
                        replacement,
                        accept_supervisorless=replacement is None,
                    )
                except TransportDeadlineExceeded as exc:
                    self._latch_fatal(exc)
                    raise
                except Exception as exc:
                    self._latch_terminal_transition_failure(exc)
                    raise
                self._last_error = None
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
            terminal_recovery = self._terminal_error is not None
            if (
                self._desired_state is DesiredRuntimeState.PAUSED
                and not terminal_recovery
            ):
                raise RuntimeControlConflictError("cannot reconnect a paused runtime")
            replacement = self._build_supervisor(self._plan)
            if replacement is None:
                raise RuntimeControlConflictError(
                    "cannot reconnect with no enabled runtime assets"
                )
            await self._stop_for_transition("reconnect")
            if terminal_recovery:
                self._desired_state = DesiredRuntimeState.RUNNING
            try:
                self._install_supervisor(replacement)
            except TransportDeadlineExceeded as exc:
                self._latch_fatal(exc)
                raise
            except Exception as exc:
                self._latch_terminal_transition_failure(exc)
                raise
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
            replacement_plan = self._compile_plan(settings)
            checkpoint = self._checkpoint()

            if not checkpoint.started:
                self._settings = settings
                self._plan = replacement_plan
                self._supervisor = None
                self._supervisor_task = None
                self._last_error = None
                if self._fatal_error is None:
                    self._terminal_error = None
                return self.snapshot()

            replacement = (
                None
                if checkpoint.desired_state is DesiredRuntimeState.PAUSED
                else self._build_supervisor(replacement_plan)
            )
            detached = False
            try:
                await self._stop_for_transition("settings replacement")
                detached = True
                self._settings = settings
                self._plan = replacement_plan
                self._install_supervisor(
                    replacement,
                    accept_supervisorless=replacement is None,
                )
                self._last_error = None
                return self.snapshot()
            except asyncio.CancelledError:
                try:
                    await self._restore_runtime_state(checkpoint)
                except BaseException as restore_exc:
                    raise RuntimeError(
                        "cancelled settings replacement could not restore runtime"
                    ) from restore_exc
                raise
            except TransportDeadlineExceeded as exc:
                self._latch_fatal(exc)
                self._supervisor = None
                self._supervisor_task = None
                raise
            except Exception as exc:
                if detached:
                    self._latch_terminal_transition_failure(exc)
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

            detached = False
            try:
                await self._stop_for_transition("recovery")
                detached = True
                offline_supervisor = self._build_supervisor(self._plan)
                if offline_supervisor is None:  # pragma: no cover
                    raise RuntimeControlConflictError(
                        "cannot recover with no enabled runtime assets"
                    )
                await offline_supervisor.execute_recovery(request)
                await self._wait_for_historical_provider_quiescence()
                self._supervisor = None
                self._desired_state = checkpoint.desired_state
                replacement = (
                    self._build_supervisor(self._plan)
                    if checkpoint.desired_state is DesiredRuntimeState.RUNNING
                    else None
                )
                self._install_supervisor(
                    replacement,
                    accept_supervisorless=replacement is None,
                )
                self._last_error = None
                return self.snapshot()
            except asyncio.CancelledError:
                try:
                    await self._restore_runtime_state(checkpoint)
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
                if detached:
                    self._latch_terminal_transition_failure(exc)
                else:
                    self._supervisor = None
                    self._supervisor_task = None
                    if self._fatal_error is None:
                        self._last_error = str(exc)
                raise


__all__ = [
    "RuntimeControlConflictError",
    "RuntimeController",
]
