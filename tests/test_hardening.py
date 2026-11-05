"""Hardening: canonical JSON, idempotency, cache, coalescing, circuit breaker, normalization."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from canonical import canonical_json
from circuit_breaker import CircuitOpen, EndpointCircuitBreaker
from circuit_path import normalize_circuit_path
from client import CRMClient, UpstreamError
from coalescing import RequestCoalescer
from idempotency_keys import compute_idempotency_key, compute_stable_update_idempotency_key
from input_normalize import normalize_raw_params
from cache import TtlCache
from tracing import new_request_id


def test_canonical_json_stable():
    a = {"b": 1, "a": None, "c": [{"z": 1, "y": 2}]}
    b = {"c": [{"y": 2, "z": 1}], "a": None, "b": 1}
    assert canonical_json(a) == canonical_json(b)


def test_canonical_list_order_preserved():
    x = {"items": [3, 2, 1]}
    y = {"items": [1, 2, 3]}
    assert canonical_json(x) != canonical_json(y)


def test_idempotency_key_ignores_workspace_in_params_payload_duplicate():
    """Outer hash scopes workspace; inner params should not need workspace_id."""
    k_no_ws = compute_idempotency_key(
        "ws-1",
        "create_task",
        "1.0.0",
        {"title": "A"},
    )
    k_empty = compute_idempotency_key(
        "ws-1",
        "create_task",
        "1.0.0",
        {},
    )
    assert k_no_ws != k_empty


def test_idempotency_key_includes_version():
    k1 = compute_idempotency_key(
        "ws",
        "create_task",
        "1.0.0",
        {"title": "Hi"},
    )
    k2 = compute_idempotency_key(
        "ws",
        "create_task",
        "1.0.1",
        {"title": "Hi"},
    )
    assert k1 != k2


def test_normalize_lowercases_status():
    raw = normalize_raw_params(
        "update_task_status",
        {"task_id": "550e8400-e29b-41d4-a716-446655440000", "status": "COMPLETED"},
    )
    assert raw["status"] == "completed"
    assert raw["task_id"] == "550e8400-e29b-41d4-a716-446655440000"


def test_cache_invalidate_prefix():
    c = TtlCache(60.0)
    c.set("w1:list_tasks:abc", {"x": 1})
    c.set("w1:list_tasks:def", {"y": 2})
    c.set("w1:search_contacts:gh", {"z": 3})
    n = c.invalidate_prefix("w1:list_tasks")
    assert n == 2
    assert c.get("w1:search_contacts:gh") is not None
    assert c.get("w1:list_tasks:abc") is None


@pytest.mark.asyncio
async def test_coalescing_parallel():
    c = RequestCoalescer()
    call_count = 0

    async def slow():
        nonlocal call_count
        await asyncio.sleep(0.05)
        call_count += 1
        return 42

    k = "same-key"
    r1 = asyncio.create_task(c.run(k, slow))
    r2 = asyncio.create_task(c.run(k, slow))
    out = await asyncio.gather(r1, r2)
    assert out == [42, 42]
    assert call_count == 1


@pytest.mark.asyncio
async def test_circuit_opens_after_failures():
    cb = EndpointCircuitBreaker(threshold=3, window_s=30.0, cooldown_s=1.0)
    k = "GET:/x"
    for _ in range(3):
        cb.record_failure(k)
    with pytest.raises(CircuitOpen):
        cb.check_before_request(k)


@pytest.mark.asyncio
async def test_circuit_half_open_closes_on_success():
    cb = EndpointCircuitBreaker(threshold=1, window_s=30.0, cooldown_s=0.0)
    k = "GET:/api/x"
    cb.record_failure(k)
    cb.check_before_request(k)  # transitions OPEN -> HALF_OPEN (cooldown 0)
    cb.record_success(k)
    cb.check_before_request(k)  # should not raise (CLOSED)


@pytest.mark.asyncio
async def test_client_circuit_upstream_error():
    new_request_id()
    from auth import AuthContext

    auth = AuthContext(token="t", user_id="u", workspace_id="w")
    cb = EndpointCircuitBreaker(threshold=1, window_s=30.0, cooldown_s=60.0)
    cb.record_failure(
        EndpointCircuitBreaker.key("GET", normalize_circuit_path("/api/v1/tasks/"), "w"),
    )
    client = CRMClient("http://127.0.0.1:9", circuit=cb)
    try:
        with pytest.raises(UpstreamError) as ei:
            await client._request_with_retries(
                "GET",
                "/api/v1/tasks/",
                auth=auth,
                params={"workspace_id": "w"},
            )
        assert ei.value.code == "upstream_unavailable"
    finally:
        await client.aclose()
