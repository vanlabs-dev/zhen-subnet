"""Webhook alerting for validator operational events.

Sends JSON payloads to a configured webhook URL on round failures,
startup, and other key events. Supports Discord, Slack, and generic
webhook receivers. Non-blocking and rate-limited.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class WebhookAlerter:
    """Non-blocking webhook alerter with rate limiting."""

    def __init__(self, webhook_url: str | None = None, cooldown_seconds: int = 600) -> None:
        """Initialize the alerter.

        Args:
            webhook_url: HTTP(S) URL to POST alerts to. None disables alerting.
            cooldown_seconds: Minimum seconds between alerts of the same type.
        """
        self.webhook_url = webhook_url
        self.cooldown_seconds = cooldown_seconds
        self._last_alert: dict[str, float] = {}

    def _is_rate_limited(self, event_type: str) -> bool:
        """Check if an event type is within the cooldown window.

        Args:
            event_type: Category string for rate limiting.

        Returns:
            True if the alert should be suppressed.
        """
        last = self._last_alert.get(event_type)
        if last is None:
            return False
        return (time.monotonic() - last) < self.cooldown_seconds

    async def send(self, event_type: str, message: str, details: dict[str, Any] | None = None) -> None:
        """Send an alert if not rate-limited.

        Args:
            event_type: Category string for rate limiting (e.g., "round_failed", "startup").
            message: Human-readable summary.
            details: Optional dict of additional context.
        """
        if self.webhook_url is None:
            return

        if self._is_rate_limited(event_type):
            logger.debug(f"Alert rate-limited: {event_type}")
            return

        is_failure = "fail" in event_type
        color = 16711680 if is_failure else 65280

        fields = [{"name": k, "value": str(v), "inline": True} for k, v in (details or {}).items()]

        payload = {
            "content": message,
            "embeds": [
                {
                    "title": f"Zhen Validator: {event_type}",
                    "description": message,
                    "fields": fields,
                    "color": color,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            ],
        }

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(self.webhook_url, json=payload)
            self._last_alert[event_type] = time.monotonic()
        except Exception as e:
            logger.warning(f"Alert webhook failed: {e}")
