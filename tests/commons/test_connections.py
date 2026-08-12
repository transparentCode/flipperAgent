"""Tests for libs.common.connections — Valkey client factory."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from libs.common.connections import create_valkey_client

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
