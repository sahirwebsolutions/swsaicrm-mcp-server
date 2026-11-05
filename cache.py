"""TTL read-through cache with prefix invalidation (tool responses only)."""

from __future__ import annotations

import hashlib
import threading
import time
from typing import Any

from canonical import canonical_json


class TtlCache:
    def __init__(self, default_ttl_s: float) -> None:
        self._default_ttl = default_ttl_s
        self._data: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def key_for(self, workspace_id: str, tool_name: str, params: dict[str, Any]) -> str:
        """Pattern: {workspace_id}:{tool_name}:{hash}"""
        h = hashlib.sha256(canonical_json(params).encode("utf-8")).hexdigest()[:32]
        return f"{workspace_id}:{tool_name}:{h}"

    def get(self, key: str) -> Any | None:
        with self._lock:
            row = self._data.get(key)
            if not row:
                return None
            exp_at, val = row
            if time.monotonic() > exp_at:
                self._data.pop(key, None)
                return None
            return val

    def set(self, key: str, value: Any, ttl_s: float | None = None) -> None:
        ttl = ttl_s if ttl_s is not None else self._default_ttl
        with self._lock:
            self._data[key] = (time.monotonic() + ttl, value)

    def invalidate_prefix(self, prefix: str) -> int:
        """Remove all keys starting with `prefix`; return count removed."""
        with self._lock:
            to_del = [k for k in self._data if k.startswith(prefix)]
            for k in to_del:
                self._data.pop(k, None)
            return len(to_del)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
