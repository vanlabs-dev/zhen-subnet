"""REST API client for the BOPTEST emulator.

Wraps BOPTEST HTTP endpoints for initialization, simulation advancement,
step configuration, and result retrieval. Uses the BOPTEST v0.8+ service
architecture where testcases are first selected to obtain a running testid.
Validators only.
"""

from __future__ import annotations

from typing import Any

import httpx


class BOPTESTClient:
    """Async REST client for a running BOPTEST service instance.

    BOPTEST v0.8+ uses a service architecture: POST /testcases/{id}/select
    returns a testid that is used in all subsequent requests.
    """

    def __init__(self, api_url: str) -> None:
        """Initialize the client with the BOPTEST service base URL.

        Args:
            api_url: Base URL of the BOPTEST service (e.g. "http://localhost:8000").
        """
        self.url = api_url.rstrip("/")
        self.client = httpx.AsyncClient(timeout=30.0)

    async def close(self) -> None:
        """Close the underlying httpx client and release connections."""
        await self.client.aclose()

    async def __aenter__(self) -> BOPTESTClient:
        """Enter async context manager."""
        return self

    async def __aexit__(self, *args: object) -> None:
        """Exit async context manager, closing the client."""
        await self.close()

    async def select_testcase(self, testcase_id: str) -> str:
        """Select a test case and start a running instance.

        Endpoint: POST /testcases/{testcase_id}/select

        Args:
            testcase_id: Identifier of the BOPTEST test case to run.

        Returns:
            The testid string for the running instance.

        Raises:
            BOPTESTError: If the request fails or returns non-200 status.
        """
        resp = await self.client.post(
            f"{self.url}/testcases/{testcase_id}/select",
            timeout=600.0,
        )
        self._check_response(resp, "select_testcase")
        data = resp.json()
        return str(data["testid"])

    async def initialize(self, testid: str, start_time: float, warmup_period: float) -> None:
        """Initialize the simulation to a start time with warmup.

        Endpoint: PUT /initialize/{testid}

        Args:
            testid: Running instance identifier from select_testcase.
            start_time: Simulation start time in seconds from beginning of year.
            warmup_period: Warmup duration in seconds before start_time.

        Raises:
            BOPTESTError: If the request fails or returns non-200 status.
        """
        resp = await self.client.put(
            f"{self.url}/initialize/{testid}",
            json={"start_time": start_time, "warmup_period": warmup_period},
        )
        self._check_response(resp, "initialize")

    async def advance(self, testid: str) -> dict[str, Any]:
        """Advance the simulation by one communication step.

        Endpoint: POST /advance/{testid}

        Args:
            testid: Running instance identifier from select_testcase.

        Returns:
            Measurement payload dict with current sensor readings.

        Raises:
            BOPTESTError: If the request fails or returns non-200 status.
        """
        resp = await self.client.post(f"{self.url}/advance/{testid}", json={})
        self._check_response(resp, "advance")
        data: dict[str, Any] = resp.json()
        payload: dict[str, Any] = data["payload"]
        return payload

    async def get_results(
        self, testid: str, point_names: list[str], start_time: float, final_time: float
    ) -> dict[str, Any]:
        """Retrieve simulation results for a time period.

        Endpoint: PUT /results/{testid}

        Args:
            testid: Running instance identifier from select_testcase.
            point_names: List of measurement point names to retrieve.
            start_time: Start of result period in seconds from beginning of year.
            final_time: End of result period in seconds from beginning of year.

        Returns:
            Dict mapping point names to lists of values.

        Raises:
            BOPTESTError: If the request fails or returns non-200 status.
        """
        resp = await self.client.put(
            f"{self.url}/results/{testid}",
            json={"point_names": point_names, "start_time": start_time, "final_time": final_time},
        )
        self._check_response(resp, "get_results")
        data: dict[str, Any] = resp.json()
        payload: dict[str, Any] = data["payload"]
        return payload

    async def set_step(self, testid: str, step: float) -> None:
        """Set the communication step size in seconds.

        Endpoint: PUT /step/{testid}

        Args:
            testid: Running instance identifier from select_testcase.
            step: Step size in seconds (e.g. 3600 for 1-hour steps).

        Raises:
            BOPTESTError: If the request fails or returns non-200 status.
        """
        resp = await self.client.put(f"{self.url}/step/{testid}", json={"step": step})
        self._check_response(resp, "set_step")

    async def get_name(self, testid: str) -> str:
        """Get the name of the running test case.

        Endpoint: GET /name/{testid}

        Args:
            testid: Running instance identifier from select_testcase.

        Returns:
            Name string of the test case.

        Raises:
            BOPTESTError: If the request fails or returns non-200 status.
        """
        resp = await self.client.get(f"{self.url}/name/{testid}")
        self._check_response(resp, "get_name")
        data: dict[str, Any] = resp.json()
        return str(data["payload"]["name"])

    async def get_measurements(self, testid: str) -> dict[str, Any]:
        """Get available measurement points for the test case.

        Endpoint: GET /measurements/{testid}

        Args:
            testid: Running instance identifier from select_testcase.

        Returns:
            Dict of available measurement points and their metadata.

        Raises:
            BOPTESTError: If the request fails or returns non-200 status.
        """
        resp = await self.client.get(f"{self.url}/measurements/{testid}")
        self._check_response(resp, "get_measurements")
        data: dict[str, Any] = resp.json()
        payload: dict[str, Any] = data["payload"]
        return payload

    async def stop(self, testid: str) -> None:
        """Stop a running test case instance.

        Endpoint: PUT /stop/{testid}

        Args:
            testid: Running instance identifier from select_testcase.

        Raises:
            BOPTESTError: If the request fails or returns non-200 status.
        """
        resp = await self.client.put(f"{self.url}/stop/{testid}")
        self._check_response(resp, "stop")

    def _check_response(self, resp: httpx.Response, operation: str) -> None:
        """Validate HTTP response and raise descriptive error on failure.

        Args:
            resp: The httpx Response object.
            operation: Name of the operation for error context.

        Raises:
            BOPTESTError: If response status is not 2xx.
        """
        if resp.status_code >= 400:
            try:
                detail = resp.json()
            except Exception:
                detail = resp.text
            raise BOPTESTError(f"BOPTEST {operation} failed (HTTP {resp.status_code}): {detail}")


class BOPTESTError(Exception):
    """Raised when a BOPTEST API request fails."""
