"""Keep tool results inside an assistant's context budget without hiding that rows were cut."""

from __future__ import annotations

import json
from typing import Any

DEFAULT_MAX_CHARS = 40_000
HARD_MAX_CHARS = 120_000


def _size(value: Any) -> int:
    return len(json.dumps(value, default=str, separators=(",", ":")))


def _largest_list(body: dict[str, Any]) -> str | None:
    best: tuple[int, str] | None = None
    for key, value in body.items():
        if isinstance(value, list) and value:
            size = _size(value)
            if best is None or size > best[0]:
                best = (size, key)
    return best[1] if best else None


def fit(body: Any, max_chars: int = DEFAULT_MAX_CHARS) -> Any:
    """Trim the biggest list in a response until it fits, and say how many rows came back."""
    limit = max(2_000, min(int(max_chars or DEFAULT_MAX_CHARS), HARD_MAX_CHARS))
    if _size(body) <= limit:
        return body
    if isinstance(body, list):
        body = {"items": body}
    if isinstance(body, dict):
        key = _largest_list(body)
        if key is not None:
            rows = body[key]
            low, high = 0, len(rows)
            while low < high:
                mid = (low + high + 1) // 2
                trial = {**body, key: rows[:mid]}
                if _size(trial) <= limit - 400:
                    low = mid
                else:
                    high = mid - 1
            if low > 0:
                return {
                    **body,
                    key: rows[:low],
                    "_truncated": {
                        "field": key,
                        "returned": low,
                        "received": len(rows),
                        "hint": "Narrow with filters, or page with limit and cursor.",
                    },
                }
    text = json.dumps(body, default=str)
    return {
        "_truncated": {
            "returned_chars": limit,
            "total_chars": len(text),
            "hint": "Narrow with filters, or fetch one record at a time.",
        },
        "partial": text[:limit],
    }
