"""Normalize URL paths for per-route circuit breaker keys (method + route shape)."""

from __future__ import annotations

import re

# Match UUIDs in path segments so POST /collection vs GET /collection/{id} stay distinct.
_UUID_SEGMENT = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-8][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}"
)


def normalize_circuit_path(path: str) -> str:
    """
    Replace each UUID in `path` with ``{id}`` so breakers are keyed by route pattern,
    not individual resources (e.g. PUT:/api/v1/opportunities/{id}).
    """
    if not path:
        return path
    return _UUID_SEGMENT.sub("{id}", path)
