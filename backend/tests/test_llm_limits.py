"""Tests for :mod:`app.services.llm_limits`.

Covers:
  - successful fetch via mocked httpx → returns requestCapacity.limit
  - HTTP error → fallback returned, cache populated with fallback
  - JSON missing requestCapacity → fallback
  - non-int limit → fallback
  - cache hit avoids second API call (TTL window)
  - cache expiry triggers re-fetch
  - missing api_key → immediate fallback (no network call)
  - force_refresh bypasses cache
  - get_cached_limit sync accessor
  - fetch_and_log_all_limits happy path returns dict
  - fetch_and_log_all_limits logs warning when configured default differs
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services import llm_limits
from app.services.llm_limits import (
    _CACHE_TTL_SECONDS,
    clear_cache,
    fetch_and_log_all_limits,
    get_cached_limit,
    get_concurrent_limit,
)


@pytest.fixture(autouse=True)
def _reset_cache() -> Any:
    """Each test starts with a clean cache."""
    clear_cache()
    yield
    clear_cache()


def _make_response(
    status_code: int = 200,
    json_data: Dict[str, Any] | None = None,
) -> MagicMock:
    """Build a fake httpx.Response-like object."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "boom", request=MagicMock(), response=resp,
        )
    else:
        resp.raise_for_status.return_value = None
    return resp


class _FakeClient:
    """Minimal AsyncClient replacement that returns a prepared response."""

    def __init__(self, response: MagicMock) -> None:
        self._response = response
        self.get = AsyncMock(return_value=response)

    async def __aenter__(self) -> "_FakeClient":
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None


# ──────────────────────────────────────────────────────────────────────
# get_concurrent_limit
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_concurrent_limit_success() -> None:
    """Successful API call returns requestCapacity.limit and caches it."""
    resp = _make_response(json_data={
        "limits": {},
        "effectiveRemaining": {"hour": 100, "day": 1000},
        "requestCapacity": {"limit": 5, "used": 1, "remaining": 4},
    })
    fake_client = _FakeClient(resp)
    with patch("httpx.AsyncClient", return_value=fake_client):
        limit = await get_concurrent_limit("glm-xlarge", api_key="key", fallback=2)
    assert limit == 5
    # Cache populated
    assert get_cached_limit("glm-xlarge") == 5


@pytest.mark.asyncio
async def test_get_concurrent_limit_http_error_returns_fallback() -> None:
    """HTTP error → fallback is returned and cached."""
    resp = _make_response(status_code=500)
    fake_client = _FakeClient(resp)
    with patch("httpx.AsyncClient", return_value=fake_client):
        limit = await get_concurrent_limit("qwen-medium", api_key="key", fallback=3)
    assert limit == 3
    assert get_cached_limit("qwen-medium") == 3


@pytest.mark.asyncio
async def test_get_concurrent_limit_missing_request_capacity() -> None:
    """Missing requestCapacity key → fallback."""
    resp = _make_response(json_data={"limits": {}})
    fake_client = _FakeClient(resp)
    with patch("httpx.AsyncClient", return_value=fake_client):
        limit = await get_concurrent_limit("glm-xlarge-fast", api_key="key", fallback=2)
    assert limit == 2


@pytest.mark.asyncio
async def test_get_concurrent_limit_non_int_limit() -> None:
    """Non-integer limit value → fallback."""
    resp = _make_response(json_data={
        "requestCapacity": {"limit": "not-a-number"},
    })
    fake_client = _FakeClient(resp)
    with patch("httpx.AsyncClient", return_value=fake_client):
        limit = await get_concurrent_limit("glm-xlarge", api_key="key", fallback=2)
    assert limit == 2


@pytest.mark.asyncio
async def test_get_concurrent_limit_network_exception_returns_fallback() -> None:
    """Network exception → fallback, no raise."""
    class _BoomClient:
        async def __aenter__(self) -> "_BoomClient":
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def get(self, *_args: Any, **_kw: Any) -> Any:
            raise httpx.ConnectError("network down")

    with patch("httpx.AsyncClient", return_value=_BoomClient()):
        limit = await get_concurrent_limit("qwen-medium", api_key="key", fallback=3)
    assert limit == 3


@pytest.mark.asyncio
async def test_get_concurrent_limit_no_api_key_returns_fallback() -> None:
    """Missing API key → immediate fallback, no network call."""
    with patch("httpx.AsyncClient") as mock_ac:
        limit = await get_concurrent_limit("glm-xlarge", api_key="", fallback=2)
    assert limit == 2
    # AsyncClient should NOT have been instantiated at all.
    assert not mock_ac.called


@pytest.mark.asyncio
async def test_get_concurrent_limit_cache_hit_avoids_api() -> None:
    """Second call within TTL window returns cached value without API call."""
    resp = _make_response(json_data={"requestCapacity": {"limit": 7}})
    fake_client = _FakeClient(resp)
    with patch("httpx.AsyncClient", return_value=fake_client):
        first = await get_concurrent_limit("glm-xlarge", api_key="key", fallback=2)
        second = await get_concurrent_limit("glm-xlarge", api_key="key", fallback=2)
    assert first == 7
    assert second == 7
    # Only one HTTP call total — second call hit cache.
    assert fake_client.get.await_count == 1


@pytest.mark.asyncio
async def test_get_concurrent_limit_cache_expiry_triggers_refetch() -> None:
    """After TTL expires, a fresh API call is made."""
    resp1 = _make_response(json_data={"requestCapacity": {"limit": 4}})
    resp2 = _make_response(json_data={"requestCapacity": {"limit": 9}})
    client1 = _FakeClient(resp1)
    client2 = _FakeClient(resp2)
    # Two distinct clients so we can assert which one was used.
    with patch("httpx.AsyncClient", side_effect=[client1, client2]):
        first = await get_concurrent_limit("glm-xlarge", api_key="key", fallback=2)
        # Manually expire cache entry.
        cached = llm_limits._limits_cache["glm-xlarge"]
        llm_limits._limits_cache["glm-xlarge"] = (cached[0], cached[1] - _CACHE_TTL_SECONDS - 1)
        second = await get_concurrent_limit("glm-xlarge", api_key="key", fallback=2)
    assert first == 4
    assert second == 9


@pytest.mark.asyncio
async def test_get_concurrent_limit_force_refresh_bypasses_cache() -> None:
    """force_refresh=True triggers a new API call even with a fresh cache."""
    resp1 = _make_response(json_data={"requestCapacity": {"limit": 3}})
    resp2 = _make_response(json_data={"requestCapacity": {"limit": 8}})
    client1 = _FakeClient(resp1)
    client2 = _FakeClient(resp2)
    with patch("httpx.AsyncClient", side_effect=[client1, client2]):
        first = await get_concurrent_limit("glm-xlarge", api_key="key", fallback=2)
        second = await get_concurrent_limit(
            "glm-xlarge", api_key="key", fallback=2, force_refresh=True,
        )
    assert first == 3
    assert second == 8


# ──────────────────────────────────────────────────────────────────────
# get_cached_limit
# ──────────────────────────────────────────────────────────────────────


def test_get_cached_limit_returns_fallback_when_uncached() -> None:
    """Uncached model → fallback."""
    assert get_cached_limit("never-fetched", fallback=99) == 99


def test_get_cached_limit_returns_fallback_when_expired() -> None:
    """Expired cache entry → fallback."""
    llm_limits._limits_cache["old-model"] = (5, time.time() - _CACHE_TTL_SECONDS - 1)
    assert get_cached_limit("old-model", fallback=2) == 2


def test_get_cached_limit_returns_cached_value() -> None:
    """Fresh cache entry → cached value."""
    llm_limits._limits_cache["fresh-model"] = (11, time.time())
    assert get_cached_limit("fresh-model", fallback=2) == 11


# ──────────────────────────────────────────────────────────────────────
# fetch_and_log_all_limits
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_and_log_all_limits_happy_path() -> None:
    """Returns dict mapping model → fetched limit for every configured model."""
    def _factory(json_data: Dict[str, Any]) -> _FakeClient:
        return _FakeClient(_make_response(json_data=json_data))

    # 4 configured models (glm-xlarge, glm-xlarge-fast, qwen-medium, qwen-medium-preview)
    responses = [
        _factory({"requestCapacity": {"limit": 2}}),  # glm-xlarge
        _factory({"requestCapacity": {"limit": 2}}),  # glm-xlarge-fast
        _factory({"requestCapacity": {"limit": 3}}),  # qwen-medium
        _factory({"requestCapacity": {"limit": 3}}),  # qwen-medium-preview
    ]
    with patch("httpx.AsyncClient", side_effect=responses):
        result = await fetch_and_log_all_limits(api_key="key")
    assert set(result.keys()) == {
        "glm-xlarge", "glm-xlarge-fast", "qwen-medium", "qwen-medium-preview",
    }
    assert result["glm-xlarge"] == 2
    assert result["qwen-medium"] == 3


@pytest.mark.asyncio
async def test_fetch_and_log_all_limits_logs_warning_on_mismatch(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When API limit != configured fallback, a WARNING is logged."""
    def _factory(limit: int) -> _FakeClient:
        return _FakeClient(_make_response(json_data={"requestCapacity": {"limit": limit}}))

    # glm-xlarge configured fallback = 2; API returns 5 → mismatch warning.
    responses = [
        _factory(5),  # glm-xlarge
        _factory(2),  # glm-xlarge-fast
        _factory(3),  # qwen-medium
        _factory(3),  # qwen-medium-preview
    ]
    with patch("httpx.AsyncClient", side_effect=responses):
        with caplog.at_level("WARNING", logger="app.services.llm_limits"):
            await fetch_and_log_all_limits(api_key="key")
    assert any(
        "differs from API limit" in rec.message and "glm-xlarge" in rec.message
        for rec in caplog.records
    )


@pytest.mark.asyncio
async def test_fetch_and_log_all_limits_swallows_errors() -> None:
    """Per-model fetch errors do not break the gather."""
    class _BoomClient:
        async def __aenter__(self) -> "_BoomClient":
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def get(self, *_args: Any, **_kw: Any) -> Any:
            raise httpx.ConnectError("network down")

    with patch("httpx.AsyncClient", return_value=_BoomClient()):
        # Should not raise — gather(return_exceptions=True) swallows.
        result = await fetch_and_log_all_limits(api_key="key")
    # All models got fallback values from their config defaults.
    assert "glm-xlarge" in result
    assert "qwen-medium" in result


def test_clear_cache() -> None:
    """clear_cache empties the in-memory cache."""
    llm_limits._limits_cache["x"] = (1, time.time())
    clear_cache()
    assert llm_limits._limits_cache == {}
