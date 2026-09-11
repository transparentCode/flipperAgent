"""Tests for libs.common.connections — Valkey client factory."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from libs.common import connections as connections_module
from libs.common.connections import (
    _validate_decision_valkey_uri,
    create_valkey_client,
    init_db_pools,
)

# ---------------------------------------------------------------------------
# create_valkey_client
# ---------------------------------------------------------------------------


class TestCreateValkeyClient:
    @pytest.mark.asyncio
    @patch("libs.common.connections.valkey")
    async def test_from_env_var(self, mock_valkey_module) -> None:
        """When VALKEY_URI env var is set, use it."""
        mock_client = AsyncMock()
        mock_valkey_module.Valkey.from_url.return_value = mock_client

        with patch(
            "libs.common.connections.os.getenv",
            side_effect=lambda k: {
                "VALKEY_URI": "redis://env-host:6379/0",
                "REDIS_URI": None,
            }.get(k),
        ):
            from libs.common.connections import create_valkey_client

            await create_valkey_client()

        mock_valkey_module.Valkey.from_url.assert_called_once_with(
            "redis://env-host:6379/0",
            decode_responses=True,
        )
        mock_client.ping.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("libs.common.connections.valkey")
    async def test_from_config(self, mock_valkey_module) -> None:
        """When no env var, fall back to ConfigManager."""
        mock_client = AsyncMock()
        mock_valkey_module.Valkey.from_url.return_value = mock_client

        mock_cfg = MagicMock()
        mock_cfg.get.return_value = "redis://config-host:6379/1"

        with patch("libs.common.connections.os.getenv", return_value=None):
            from libs.common.connections import create_valkey_client

            await create_valkey_client(config_mgr=mock_cfg)

        mock_valkey_module.Valkey.from_url.assert_called_once_with(
            "redis://config-host:6379/1",
            decode_responses=True,
        )

    @pytest.mark.asyncio
    @patch("libs.common.connections.valkey")
    async def test_masks_password_in_log(self, mock_valkey_module) -> None:
        """URI with user:pass@host should only log the host part."""
        mock_client = AsyncMock()
        mock_valkey_module.Valkey.from_url.return_value = mock_client

        with (
            patch(
                "libs.common.connections.os.getenv",
                side_effect=lambda k: {
                    "VALKEY_URI": "redis://user:secret@myhost:6379/0",
                    "REDIS_URI": None,
                }.get(k),
            ),
            patch("libs.common.connections.logger") as mock_logger,
        ):
            await create_valkey_client()

            # The info call should contain the masked URI (host part only)
            log_calls = [str(c) for c in mock_logger.info.call_args_list]
            # Should contain 'myhost' but NOT 'secret'
            connect_log = log_calls[0]
            assert "myhost" in connect_log
            assert "secret" not in connect_log

    @pytest.mark.asyncio
    @patch("libs.common.connections.valkey")
    async def test_failed_candidate_is_closed_before_retry(
        self,
        mock_valkey_module,
    ) -> None:
        first_client = AsyncMock()
        first_client.ping.side_effect = ConnectionError("broker unavailable")
        second_client = AsyncMock()
        mock_valkey_module.Valkey.from_url.side_effect = [
            first_client,
            second_client,
        ]

        with (
            patch(
                "libs.common.connections.os.getenv",
                side_effect=lambda key: {
                    "VALKEY_URI": "redis://localhost:6380/0",
                    "REDIS_URI": None,
                }.get(key),
            ),
            patch(
                "libs.common.connections.asyncio.sleep",
                new_callable=AsyncMock,
            ),
        ):
            result = await create_valkey_client()

        assert result is second_client
        first_client.aclose.assert_awaited_once()
        second_client.aclose.assert_not_awaited()

    @pytest.mark.asyncio
    @patch("libs.common.connections.valkey")
    async def test_cancellation_closes_candidate_and_propagates(
        self,
        mock_valkey_module,
    ) -> None:
        client = AsyncMock()
        ping_started = asyncio.Event()

        async def blocked_ping() -> None:
            ping_started.set()
            await asyncio.Event().wait()

        client.ping.side_effect = blocked_ping
        mock_valkey_module.Valkey.from_url.return_value = client

        with patch(
            "libs.common.connections.os.getenv",
            side_effect=lambda key: {
                "VALKEY_URI": "redis://localhost:6380/0",
                "REDIS_URI": None,
            }.get(key),
        ):
            task = asyncio.create_task(create_valkey_client())
            await ping_started.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        client.aclose.assert_awaited_once()
        mock_valkey_module.Valkey.from_url.assert_called_once()

    @pytest.mark.asyncio
    @patch("libs.common.connections.valkey")
    async def test_default_failed_candidate_close_preserves_cancellation(
        self,
        mock_valkey_module,
    ) -> None:
        client = AsyncMock()
        close_started = asyncio.Event()
        client.ping.side_effect = ConnectionError("broker unavailable")

        async def blocked_close() -> None:
            close_started.set()
            await asyncio.Event().wait()

        client.aclose.side_effect = blocked_close
        mock_valkey_module.Valkey.from_url.return_value = client

        with patch(
            "libs.common.connections.os.getenv",
            side_effect=lambda key: {
                "VALKEY_URI": "redis://localhost:6380/0",
                "REDIS_URI": None,
            }.get(key),
        ):
            task = asyncio.create_task(create_valkey_client())
            await close_started.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        mock_valkey_module.Valkey.from_url.assert_called_once()
        client.aclose.assert_awaited_once()

    @pytest.mark.parametrize(
        "uri",
        [
            "redis://localhost:6379/0?retry_on_timeout=enabled",
            "redis://localhost:6379/0?retry_on_timeout=yes&retry_on_timeout=no",
            "redis://localhost:6379/0?retry_on_error=TimeoutError",
            "redis://localhost:6379/0?retry=5",
        ],
    )
    def test_decision_uri_rejects_all_native_retry_overrides(self, uri: str) -> None:
        with pytest.raises(ValueError, match="retry"):
            _validate_decision_valkey_uri(uri, 5.0)

    def test_decision_uri_uses_native_parser_for_socket_values(self) -> None:
        _validate_decision_valkey_uri(
            "redis://localhost:6379/0?socket_timeout=5%2E0",
            5.0,
        )
        with pytest.raises(ValueError, match="socket_timeout"):
            _validate_decision_valkey_uri(
                "redis://localhost:6379/0?socket_timeout=5&socket_timeout=5",
                5.0,
            )

    @pytest.mark.asyncio
    @patch("libs.common.connections.valkey")
    async def test_decision_factory_sets_native_no_retry_socket_options(
        self,
        mock_valkey_module,
    ) -> None:
        client = AsyncMock()
        mock_valkey_module.Valkey.from_url.return_value = client
        with patch(
            "libs.common.connections.os.getenv",
            side_effect=lambda key: {
                "VALKEY_URI": "redis://localhost:6379/0",
                "REDIS_URI": None,
            }.get(key),
        ):
            await create_valkey_client(io_timeout_seconds=5.0)

        mock_valkey_module.Valkey.from_url.assert_called_once_with(
            "redis://localhost:6379/0",
            decode_responses=True,
            socket_timeout=5.0,
            socket_connect_timeout=5.0,
            retry_on_timeout=False,
            retry_on_error=[],
        )

    @pytest.mark.asyncio
    @patch("libs.common.connections.valkey")
    async def test_bounded_candidate_cleanup_uses_supplied_callback(
        self,
        mock_valkey_module,
    ) -> None:
        first_client = AsyncMock()
        first_client.ping.side_effect = ConnectionError("broker unavailable")
        second_client = AsyncMock()
        mock_valkey_module.Valkey.from_url.side_effect = [
            first_client,
            second_client,
        ]
        cleanup_calls: list[tuple[object, bool]] = []

        async def cleanup(awaitable, retrying: bool) -> None:
            cleanup_calls.append((awaitable, retrying))
            await awaitable

        with (
            patch(
                "libs.common.connections.os.getenv",
                side_effect=lambda key: {
                    "VALKEY_URI": "redis://localhost:6380/0",
                    "REDIS_URI": None,
                }.get(key),
            ),
            patch(
                "libs.common.connections.asyncio.sleep",
                new_callable=AsyncMock,
            ),
        ):
            result = await create_valkey_client(
                io_timeout_seconds=5.0,
                cleanup_callback=cleanup,
            )

        assert result is second_client
        assert len(cleanup_calls) == 1
        assert cleanup_calls[0][1] is True
        first_client.aclose.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("libs.common.connections.valkey")
    async def test_bounded_retry_reaches_third_candidate_after_confirmed_cleanup(
        self,
        mock_valkey_module,
        monkeypatch,
    ) -> None:
        candidates = [AsyncMock(), AsyncMock(), AsyncMock()]
        candidates[0].ping.side_effect = TimeoutError("first")
        candidates[1].ping.side_effect = TimeoutError("second")
        mock_valkey_module.Valkey.from_url.side_effect = candidates
        retrying_flags: list[bool] = []

        async def cleanup(awaitable, retrying: bool) -> None:
            retrying_flags.append(retrying)
            await awaitable

        monkeypatch.setattr(connections_module, "_VALKEY_CONNECT_RETRIES", 3)
        monkeypatch.setattr(
            connections_module, "_VALKEY_RETRY_DELAYS", [0.03, 0.03, 0.03]
        )
        with (
            patch(
                "libs.common.connections.os.getenv",
                side_effect=lambda key: {
                    "VALKEY_URI": "redis://localhost:6380/0",
                    "REDIS_URI": None,
                }.get(key),
            ),
            patch(
                "libs.common.connections.asyncio.sleep",
                new_callable=AsyncMock,
            ) as sleep,
        ):
            result = await create_valkey_client(
                io_timeout_seconds=0.02,
                cleanup_callback=cleanup,
            )

        assert result is candidates[2]
        assert retrying_flags == [True, True]
        assert sleep.await_count == 2
        for candidate in candidates[:2]:
            candidate.aclose.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("libs.common.connections.valkey")
    async def test_bounded_terminal_failure_keeps_final_cleanup_budget_and_skips_final_delay(
        self,
        mock_valkey_module,
        monkeypatch,
    ) -> None:
        candidates = [AsyncMock(), AsyncMock(), AsyncMock()]
        for candidate in candidates:
            candidate.ping.side_effect = TimeoutError("unavailable")
        mock_valkey_module.Valkey.from_url.side_effect = candidates
        retrying_flags: list[bool] = []

        async def cleanup(awaitable, retrying: bool) -> None:
            retrying_flags.append(retrying)
            await awaitable

        monkeypatch.setattr(connections_module, "_VALKEY_CONNECT_RETRIES", 3)
        monkeypatch.setattr(
            connections_module, "_VALKEY_RETRY_DELAYS", [0.03, 0.03, 0.03]
        )
        with (
            patch(
                "libs.common.connections.os.getenv",
                side_effect=lambda key: {
                    "VALKEY_URI": "redis://localhost:6380/0",
                    "REDIS_URI": None,
                }.get(key),
            ),
            patch(
                "libs.common.connections.asyncio.sleep",
                new_callable=AsyncMock,
            ) as sleep,
            pytest.raises(ConnectionError, match="Failed to connect to Valkey"),
        ):
            await create_valkey_client(
                io_timeout_seconds=0.02,
                cleanup_callback=cleanup,
            )

        assert retrying_flags == [True, True, False]
        assert sleep.await_count == 2
        for candidate in candidates:
            candidate.aclose.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_installed_valkey_resp_blackhole_obeys_wire_timeout(
        self,
        monkeypatch,
    ) -> None:
        requests: list[bytes] = []
        writers: list[asyncio.StreamWriter] = []
        stop = asyncio.Event()
        request_seen = asyncio.Event()

        async def blackhole(
            reader: asyncio.StreamReader,
            writer: asyncio.StreamWriter,
        ) -> None:
            writers.append(writer)
            try:
                requests.append(await asyncio.wait_for(reader.read(128), 0.2))
                request_seen.set()
                await stop.wait()
            finally:
                writer.close()
                await writer.wait_closed()

        server = await asyncio.start_server(blackhole, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]

        async def cleanup(awaitable, _retrying: bool) -> None:
            await asyncio.wait_for(awaitable, 0.05)

        monkeypatch.setattr(connections_module, "_VALKEY_CONNECT_RETRIES", 1)
        monkeypatch.setattr(connections_module, "_VALKEY_RETRY_DELAYS", [0])
        try:
            with patch(
                "libs.common.connections.os.getenv",
                side_effect=lambda key: {
                    "VALKEY_URI": f"redis://127.0.0.1:{port}/0",
                    "REDIS_URI": None,
                }.get(key),
            ):
                started = asyncio.get_running_loop().time()
                with pytest.raises(ConnectionError):
                    await create_valkey_client(
                        io_timeout_seconds=0.05,
                        cleanup_callback=cleanup,
                    )
                elapsed = asyncio.get_running_loop().time() - started
        finally:
            try:
                await asyncio.wait_for(request_seen.wait(), 0.2)
            except TimeoutError:
                pass
            stop.set()
            for writer in writers:
                writer.close()
            await asyncio.gather(
                *(writer.wait_closed() for writer in writers),
                return_exceptions=True,
            )
            server.close()
            await server.wait_closed()

        assert elapsed < 0.5
        assert any(
            b"CLIENT" in request and b"SETINFO" in request for request in requests
        )

    @pytest.mark.asyncio
    async def test_init_db_pools_omitted_contract_returns_none_and_omits_options(
        self,
    ) -> None:
        with patch(
            "libs.common.connections.DBPoolManager.init_pools",
            new_callable=AsyncMock,
        ) as init:
            assert await init_db_pools() is None
        init.assert_awaited_once_with(config_manager=None)
