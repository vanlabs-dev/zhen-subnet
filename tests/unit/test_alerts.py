"""Unit tests for webhook alerting."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from validator.alerts import WebhookAlerter


@pytest.mark.asyncio
async def test_no_webhook_is_noop() -> None:
    """WebhookAlerter with no URL sends nothing and doesn't error."""
    alerter = WebhookAlerter(webhook_url=None)
    # Should complete without error or making any HTTP calls
    await alerter.send("test_event", "test message", {"key": "value"})


@pytest.mark.asyncio
async def test_rate_limiting() -> None:
    """Second alert of same type within cooldown is suppressed."""
    alerter = WebhookAlerter(webhook_url="http://example.com/webhook", cooldown_seconds=600)

    with patch("validator.alerts.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=None)

        await alerter.send("round_failed", "first alert")
        await alerter.send("round_failed", "second alert (should be suppressed)")

        # Only one POST call should have been made
        assert mock_client.post.call_count == 1


@pytest.mark.asyncio
async def test_different_types_not_rate_limited() -> None:
    """Different event types are rate-limited independently."""
    alerter = WebhookAlerter(webhook_url="http://example.com/webhook", cooldown_seconds=600)

    with patch("validator.alerts.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=None)

        await alerter.send("round_failed", "failure alert")
        await alerter.send("weights_failed", "weights alert")

        # Both should have been sent (different event types)
        assert mock_client.post.call_count == 2


@pytest.mark.asyncio
async def test_rate_limit_expires() -> None:
    """Alert sends again after cooldown expires."""
    alerter = WebhookAlerter(webhook_url="http://example.com/webhook", cooldown_seconds=0)

    with patch("validator.alerts.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=None)

        await alerter.send("test_event", "first")
        # With cooldown=0, second alert should also send
        await alerter.send("test_event", "second")

        assert mock_client.post.call_count == 2
