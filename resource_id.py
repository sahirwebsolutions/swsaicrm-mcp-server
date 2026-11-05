"""Best-effort resource id extraction from FastAPI JSON bodies."""

from __future__ import annotations

from typing import Any


def resource_id_from_response(body: dict[str, Any]) -> str | None:
    if not isinstance(body, dict):
        return None
    inner = body.get("data")
    if isinstance(inner, dict):
        rid = inner.get("id")
        if rid is not None:
            return str(rid)
    for key in ("id", "opportunity_id", "contact_id", "board_id", "task_id", "stage_id"):
        v = body.get(key)
        if v is not None:
            return str(v)
    return None
