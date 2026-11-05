"""
Normalize tool inputs before validation/hashing.

ONLY: enum-like fields (lowercase) and UUID formatting.
NEVER: mutate free text, names, titles, descriptions, notes, search strings, etc.
"""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-8][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)

# Fields where CRM stores controlled vocabulary (safe to lowercase+strip)
_ENUM_KEYS = frozenset(
    {
        "status",
        "priority",
        "task_type",
        "type",
        "stage",
        "sort_order",
        "currency",
    }
)


def normalize_raw_params(tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in sorted(params.keys()):
        v = params[k]
        nk = k.strip() if isinstance(k, str) else k
        out[nk] = _normalize_value(nk, v)
    return out


def _normalize_value(key: str, value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return {str(sk): _normalize_value(str(sk), sv) for sk, sv in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize_value(key, item) for item in value]
    if isinstance(value, UUID):
        return str(value).lower()
    if isinstance(value, str):
        lk = key.lower()
        if lk in _ENUM_KEYS:
            return value.strip().lower()
        if lk.endswith("_id") or lk == "id":
            s = value.strip()
            if _UUID_RE.match(s):
                return s.lower()
            return value
        return value
    return value
