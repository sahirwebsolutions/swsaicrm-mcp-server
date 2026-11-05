"""ASGI / tool execution shared state (Bearer token source)."""

from __future__ import annotations

import contextvars
import os

bearer_header_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("bearer_header", default=None)


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
