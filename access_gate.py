"""Ask the CRM which tools this connection may call. An empty set means no."""

from __future__ import annotations

import hashlib
from typing import Any

from auth import AuthContext
from client import CRMClient, UpstreamError

ALLOW_TTL_S = 45.0
DENY_TTL_S = 15.0


async def allowed_tools(
    client: CRMClient,
    cache: Any,
    auth: AuthContext,
) -> tuple[set[str], str | None]:
    key = "api-allow:" + hashlib.sha256(auth.token.encode("utf-8")).hexdigest()
    cached = cache.get(key)
    if isinstance(cached, dict):
        return set(cached.get("tools") or []), cached.get("error")

    try:
        response = await client._request_with_retries(
            "GET",
            "/api/v1/api-access/session",
            auth=auth,
            params={"workspace_id": auth.workspace_id},
        )
        body = client.raise_for_status(response)
    except UpstreamError as exc:
        cache.set(key, {"tools": [], "error": exc.message}, ttl_s=DENY_TTL_S)
        return set(), exc.message or "This connection cannot use the API"

    names = [str(name) for name in (body.get("tools") or []) if name]
    cache.set(key, {"tools": names, "error": None}, ttl_s=ALLOW_TTL_S)
    return set(names), None
