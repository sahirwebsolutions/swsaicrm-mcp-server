"""Map upstream HTTP status to stable MCP-facing error codes."""

from __future__ import annotations

from typing import Any


def http_status_to_code(status: int | None) -> str:
    """Map HTTP status to MCP-facing codes (includes upstream_unavailable when circuit is open — surfaced via UpstreamError.code)."""
    if status is None:
        return "upstream_error"
    if status == 400:
        return "invalid_params"
    if status == 401:
        return "auth_failed"
    if status == 403:
        return "permission_denied"
    if status == 404:
        return "not_found"
    if status == 429:
        return "rate_limited"
    if status >= 500:
        return "upstream_error"
    return "upstream_error"


def safe_upstream_detail(body: Any) -> str:
    """Avoid leaking stack traces: prefer short string detail when present."""
    if isinstance(body, dict):
        d = body.get("detail")
        if isinstance(d, str) and d.strip():
            return d[:500]
        err = body.get("error")
        if isinstance(err, str) and err.strip():
            return err[:500]
    return "request failed"
