"""Lightweight HTTP health check server for monitoring.

Runs on a configurable port (default 8080) and exposes:
  GET /health -> 200 OK with JSON status
"""

from __future__ import annotations

import json
import logging
import time

from aiohttp import web

logger = logging.getLogger(__name__)


class HealthServer:
    """HTTP health check endpoint for validator monitoring."""

    def __init__(self, port: int = 8080, bind_address: str = "127.0.0.1") -> None:
        """Initialize the health server.

        Args:
            port: TCP port to listen on.
            bind_address: Interface to bind to. Defaults to loopback so the
                endpoint is not exposed to the network. Operators who need
                external monitoring can pass "0.0.0.0".
        """
        self.port = port
        self.bind_address = bind_address
        self.start_time = time.time()
        self.last_round_time: float = 0.0
        self.round_count: int = 0
        self.last_round_status: str = "pending"

    def record_round(self, success: bool) -> None:
        """Record completion of a round for health reporting.

        Args:
            success: Whether the round completed successfully.
        """
        self.last_round_time = time.time()
        self.round_count += 1
        self.last_round_status = "ok" if success else "failed"

    async def _handle_health(self, request: web.Request) -> web.Response:
        """Handle GET /health requests."""
        uptime = time.time() - self.start_time
        status = {
            "status": "healthy",
            "uptime_seconds": int(uptime),
            "rounds_completed": self.round_count,
            "last_round_status": self.last_round_status,
            "seconds_since_last_round": (int(time.time() - self.last_round_time) if self.last_round_time > 0 else None),
        }
        return web.Response(
            text=json.dumps(status),
            content_type="application/json",
        )

    async def start(self) -> None:
        """Start the health check server in the background."""
        app = web.Application()
        app.router.add_get("/health", self._handle_health)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, self.bind_address, self.port)
        await site.start()
        logger.info(f"Health check server started on {self.bind_address}:{self.port}")
