from unittest.mock import AsyncMock, patch

import httpx
import pytest

from auth import AuthContext
from client import CRMClient
from tracing import new_request_id


@pytest.mark.asyncio
async def test_get_retries_on_503():
    new_request_id()
    auth = AuthContext(token="t", user_id="u", workspace_id="w")

    responses = [
        httpx.Response(503, json={"detail": "unavailable"}),
        httpx.Response(200, json={"ok": True}),
    ]

    c = CRMClient("http://localhost:9999", timeout_s=5.0, max_retries=2)
    try:
        with patch.object(c._client, "request", new=AsyncMock(side_effect=responses)):
            r = await c._request_with_retries(
                "GET",
                "/api/v1/contacts",
                auth=auth,
                params={"workspace_id": "w"},
            )
        assert r.status_code == 200
        assert r.json() == {"ok": True}
    finally:
        await c.aclose()


@pytest.mark.asyncio
async def test_post_without_idempotency_no_retry_on_503():
    new_request_id()
    auth = AuthContext(token="t", user_id="u", workspace_id="w")
    responses = [httpx.Response(503, json={"detail": "unavailable"})]

    c = CRMClient("http://localhost:9999", timeout_s=5.0, max_retries=2)
    try:
        with patch.object(c._client, "request", new=AsyncMock(side_effect=responses)):
            r = await c._request_with_retries(
                "POST",
                "/api/v1/tasks/",
                auth=auth,
                json_body={"title": "x"},
                idempotency_key=None,
            )
        assert r.status_code == 503
    finally:
        await c.aclose()


@pytest.mark.asyncio
async def test_post_with_idempotency_retries():
    new_request_id()
    auth = AuthContext(token="t", user_id="u", workspace_id="w")
    responses = [
        httpx.Response(503),
        httpx.Response(200, json={"done": True}),
    ]
    c = CRMClient("http://localhost:9999", timeout_s=5.0, max_retries=2)
    try:
        with patch.object(c._client, "request", new=AsyncMock(side_effect=responses)):
            r = await c._request_with_retries(
                "POST",
                "/api/v1/tasks/",
                auth=auth,
                json_body={"title": "x"},
                idempotency_key="idem-1",
            )
        assert r.status_code == 200
    finally:
        await c.aclose()
