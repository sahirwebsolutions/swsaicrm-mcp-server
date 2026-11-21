"""ASGI / tool execution shared state (Bearer token source)."""

from __future__ import annotations

import base64
import contextvars
import json
import os

bearer_header_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("bearer_header", default=None)
# Caller identity for cache keys: results visible to one member must not serve another.
cache_principal_var: contextvars.ContextVar[str] = contextvars.ContextVar("cache_principal", default="")


def is_api_connection_token() -> bool:
    """Routing hint only (unverified claim peek). The CRM verifies the token on every call."""
    token = resolve_raw_bearer_token()
    if not token:
        return False
    parts = token.split(".")
    if len(parts) != 3:
        return False
    segment = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        claims = json.loads(base64.urlsafe_b64decode(segment.encode("ascii")))
    except Exception:
        return False
    return isinstance(claims, dict) and claims.get("token_use") == "api_connection"


def resolve_raw_bearer_token() -> str | None:
    """Prefer incoming HTTP Authorization header; fallback to stdio env."""
    h = bearer_header_var.get()
    if h and h.strip():
        if h.lower().startswith("bearer "):
            return h.split(" ", 1)[1].strip()
        return h.strip()
    env_tok = os.environ.get("MCP_BEARER_TOKEN") or os.environ.get("CRM_JWT")
    if env_tok and env_tok.strip():
        if env_tok.lower().startswith("bearer "):
            return env_tok.split(" ", 1)[1].strip()
        return env_tok.strip()
    return None
