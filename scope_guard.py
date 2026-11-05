"""Reject tool arguments that attempt to override tenancy or user identity."""

from __future__ import annotations

from typing import Any

_FORBIDDEN = frozenset(
    {
        "workspace_id",
        "user_id",
        "profile_id",
        "current_workspace_id",
        "x_workspace_id",
        "x_user_id",
    }
)


def is_identity_key(key: str) -> bool:
    """True if ``key`` is a forbidden tenancy / identity override (case-insensitive, ``-`` / ``_`` normalized)."""
    k = str(key).lower().replace("-", "_")
    return k in _FORBIDDEN


def forbidden_identity_argument(args: dict[str, Any]) -> str | None:
    """
    Return the first forbidden key if present (case-insensitive, ``-`` / ``_`` normalized).

    JWT supplies workspace and user; tools must not accept parallel identity fields.
    """
    for raw in args:
        if is_identity_key(str(raw)):
            return str(raw)
    return None
