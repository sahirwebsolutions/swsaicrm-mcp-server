"""Cross-module invalidation, write dedupe, stable update idempotency, partial failure."""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest

from cache import TtlCache
from cache_invalidation_map import invalidate_by_tool
from circuit_path import normalize_circuit_path
from client import CRMClient
from idempotency_keys import compute_stable_update_idempotency_key
from tracing import new_request_id
from write_guard import WriteGuard


def test_normalize_circuit_path_collapses_uuid():
    uid = "550e8400-e29b-41d4-a716-446655440000"
    p = f"/api/v1/opportunities/{uid}"
    assert normalize_circuit_path(p) == "/api/v1/opportunities/{id}"


def test_stable_update_idempotency_same_for_payload_variant():
    rid = "550e8400-e29b-41d4-a716-446655440000"
    k1 = compute_stable_update_idempotency_key(
        "w", "update_deal", "1.0.0", rid, "update_fields"
    )
    k2 = compute_stable_update_idempotency_key(
        "w", "update_deal", "1.0.0", rid, "update_fields"
    )
    assert k1 == k2


def test_invalidate_by_tool_cross_module_on_create_deal():
    c = TtlCache(60.0)
    w = "ws1"
    c.set(f"{w}:list_deals:aa", {"x": 1})
    c.set(f"{w}:list_pipelines:bb", {"y": 2})
    c.set(f"{w}:search_contacts:cc", {"z": 3})
    c.set(f"{w}:list_tasks:dd", {"t": 4})
    n = invalidate_by_tool(c, w, "create_deal")
    assert n >= 3
    assert c.get(f"{w}:list_tasks:dd") is not None


def test_write_guard_reuses_within_window():
    g = WriteGuard(window_s=30.0)
    ws = "w"
    tool = "create_contact"
    params = {"name": "A", "email": "a@b.co"}
    assert g.try_hit(ws, tool, params) is None
    g.record(ws, tool, params, {"data": {"ok": True}, "_meta": {}})
    hit = g.try_hit(ws, tool, params)
    assert hit is not None
    assert hit["data"]["ok"] is True


@pytest.mark.asyncio
async def test_idempotent_timeout_returns_unknown_body():
    new_request_id()
    from auth import AuthContext

    auth = AuthContext(token="t", user_id="u", workspace_id="w")

    async def boom(*_a, **_k):
        raise httpx.TimeoutException("timeout")

    client = CRMClient("http://127.0.0.1:9", max_retries=0)
    client._client.request = AsyncMock(side_effect=boom)
    try:
        resp = await client._request_with_retries(
            "POST",
            "/api/v1/opportunities",
            auth=auth,
            idempotency_key="abc" * 20,
        )
        body = client.raise_for_status(resp)
        assert body.get("status") == "unknown"
        assert "Retry is safe" in (body.get("message") or "")
    finally:
        await client.aclose()
