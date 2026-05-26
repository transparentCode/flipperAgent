"""Tests for libs.common.connections — Valkey client factory."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


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

        with patch("libs.common.connections.os.getenv", side_effect=lambda k: {
            "VALKEY_URI": "redis://env-host:6379/0",
            "REDIS_URI": None,
        }.get(k)):
            from libs.common.connections import create_valkey_client
            client = await create_valkey_client()

        mock_valkey_module.Valkey.from_url.assert_called_once_with(
            "redis://env-host:6379/0", decode_responses=True,
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
            client = await create_valkey_client(config_mgr=mock_cfg)

        mock_valkey_module.Valkey.from_url.assert_called_once_with(
            "redis://config-host:6379/1", decode_responses=True,
        )

    @pytest.mark.asyncio
    @patch("libs.common.connections.valkey")
    async def test_masks_password_in_log(self, mock_valkey_module) -> None:
        """URI with user:pass@host should only log the host part."""
        mock_client = AsyncMock()
        mock_valkey_module.Valkey.from_url.return_value = mock_client

        with patch("libs.common.connections.os.getenv", side_effect=lambda k: {
            "VALKEY_URI": "redis://user:secret@myhost:6379/0",
            "REDIS_URI": None,
        }.get(k)):
            with patch("libs.common.connections.logger") as mock_logger:
                from libs.common.connections import create_valkey_client
                await create_valkey_client()

                # The info call should contain the masked URI (host part only)
                log_calls = [str(c) for c in mock_logger.info.call_args_list]
                # Should contain 'myhost' but NOT 'secret'
                connect_log = log_calls[0]
                assert "myhost" in connect_log
                assert "secret" not in connect_log
