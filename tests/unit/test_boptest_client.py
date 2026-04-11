"""Unit tests for the BOPTEST REST client.

Tests mock httpx responses to verify client behavior without
requiring a running BOPTEST instance.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from validator.emulator.boptest_client import BOPTESTClient, BOPTESTError


@pytest.fixture
def client() -> BOPTESTClient:
    """Create a BOPTESTClient pointed at a fake URL."""
    return BOPTESTClient("http://localhost:8000")


def _mock_response(status_code: int = 200, json_data: dict[str, object] | None = None, text: str = "") -> httpx.Response:
    """Build a fake httpx.Response."""
    import json as json_mod

    content = json_mod.dumps(json_data).encode() if json_data is not None else text.encode()
    resp = httpx.Response(
        status_code=status_code,
        content=content,
        headers={"content-type": "application/json"} if json_data is not None else {},
        request=httpx.Request("GET", "http://localhost:8000"),
    )
    return resp


@pytest.mark.asyncio
async def test_select_testcase(client: BOPTESTClient) -> None:
    """POST /testcases/{id}/select returns a testid."""
    mock_resp = _mock_response(200, json_data={"testid": "abc-123"})
    with patch.object(client.client, "post", new_callable=AsyncMock, return_value=mock_resp):
        testid = await client.select_testcase("bestest_hydronic_heat_pump")
    assert testid == "abc-123"


@pytest.mark.asyncio
async def test_initialize(client: BOPTESTClient) -> None:
    """PUT /initialize/{testid} completes without error on 200."""
    mock_resp = _mock_response(200, json_data={"status": "ok"})
    with patch.object(client.client, "put", new_callable=AsyncMock, return_value=mock_resp):
        await client.initialize("abc-123", start_time=0.0, warmup_period=86400.0)


@pytest.mark.asyncio
async def test_advance(client: BOPTESTClient) -> None:
    """POST /advance/{testid} returns measurement payload."""
    payload = {"zone_temp": 21.5, "heating_power": 1200.0, "time": 3600.0}
    mock_resp = _mock_response(200, json_data={"payload": payload})
    with patch.object(client.client, "post", new_callable=AsyncMock, return_value=mock_resp):
        result = await client.advance("abc-123")
    assert result == payload
    assert result["zone_temp"] == 21.5


@pytest.mark.asyncio
async def test_get_results(client: BOPTESTClient) -> None:
    """PUT /results/{testid} returns data for the requested points."""
    payload = {
        "zone_air_temperature_C": [20.0, 20.5, 21.0],
        "time": [0.0, 3600.0, 7200.0],
    }
    mock_resp = _mock_response(200, json_data={"payload": payload})
    with patch.object(client.client, "put", new_callable=AsyncMock, return_value=mock_resp):
        result = await client.get_results(
            "abc-123",
            point_names=["zone_air_temperature_C"],
            start_time=0.0,
            final_time=7200.0,
        )
    assert "zone_air_temperature_C" in result
    assert len(result["zone_air_temperature_C"]) == 3


@pytest.mark.asyncio
async def test_get_measurements(client: BOPTESTClient) -> None:
    """GET /measurements/{testid} returns available measurement points."""
    payload = {
        "zone_air_temperature_C": {"Unit": "K", "Description": "Zone air temperature"},
        "heating_power_W": {"Unit": "W", "Description": "Heating power"},
    }
    mock_resp = _mock_response(200, json_data={"payload": payload})
    with patch.object(client.client, "get", new_callable=AsyncMock, return_value=mock_resp):
        result = await client.get_measurements("abc-123")
    assert "zone_air_temperature_C" in result
    assert "heating_power_W" in result


@pytest.mark.asyncio
async def test_error_handling(client: BOPTESTClient) -> None:
    """Non-200 response raises BOPTESTError with descriptive message."""
    mock_resp = _mock_response(500, json_data={"message": "Internal server error"})
    with (
        patch.object(client.client, "post", new_callable=AsyncMock, return_value=mock_resp),
        pytest.raises(BOPTESTError, match="advance failed.*500"),
    ):
        await client.advance("abc-123")


@pytest.mark.asyncio
async def test_timeout(client: BOPTESTClient) -> None:
    """Timeout raises httpx.TimeoutException."""
    with (
        patch.object(client.client, "post", new_callable=AsyncMock, side_effect=httpx.TimeoutException("timed out")),
        pytest.raises(httpx.TimeoutException),
    ):
        await client.advance("abc-123")
