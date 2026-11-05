"""Canonical JSON for stable hashing (idempotency, coalescing)."""

from __future__ import annotations

import json
from typing import Any


def normalize_for_hash(data: Any) -> Any:
    """
    Recursively normalize for hashing:
    - dicts: sorted keys
    - lists/tuples: preserve order (never auto-sort)
    - None preserved
    - primitives unchanged (stripping/lowercasing belongs in input_normalize for enums only)
    """
    if data is None:
        return None
    if isinstance(data, dict):
        return {str(k): normalize_for_hash(data[k]) for k in sorted(data.keys(), key=str)}
    if isinstance(data, (list, tuple)):
        return [normalize_for_hash(x) for x in data]
    if isinstance(data, bool):
        return data
    if isinstance(data, (int, float)):
        return data
    if isinstance(data, str):
        return data
    return data


def canonical_json(data: dict[str, Any]) -> str:
    """Stable JSON: recursive key sorting, list order preserved, nulls preserved."""
    body = normalize_for_hash(dict(data))
    return json.dumps(
        body,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
