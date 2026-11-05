"""Short-window dedupe of identical write tool calls (anti AI spam)."""

from __future__ import annotations

import hashlib
import threading
import time
from typing import Any

from canonical import canonical_json


class WriteGuard:
    """
    Key: workspace_id + tool + semantic hash(params).

    If the same write repeats within ``window_s``, return the last successful response.
    """

    def __init__(self, window_s: float = 8.0) -> None:
        self._window_s = float(window_s)
        self._lock = threading.Lock()
        # key -> (monotonic_expiry, cached full tool result {data, _meta})
        self._recent: dict[str, tuple[float, dict[str, Any]]] = {}

    @staticmethod
    def _semantic_key(workspace_id: str, tool_name: str, params: dict[str, Any]) -> str:
        h = hashlib.sha256(
            canonical_json(dict(params)).encode("utf-8"),
        ).hexdigest()
        return f"{workspace_id}:{tool_name}:{h}"

    def try_hit(self, workspace_id: str, tool_name: str, params: dict[str, Any]) -> dict[str, Any] | None:
        if self._window_s <= 0:
            return None
        sk = self._semantic_key(workspace_id, tool_name, params)
        now = time.monotonic()
        with self._lock:
            self._prune_unlocked(now)
            row = self._recent.get(sk)
            if not row:
                return None
            exp_at, cached = row
            if now > exp_at:
                self._recent.pop(sk, None)
                return None
            return dict(cached)

    def record(
        self,
        workspace_id: str,
        tool_name: str,
        params: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        sk = self._semantic_key(workspace_id, tool_name, params)
        if self._window_s <= 0:
            return
        exp = time.monotonic() + max(1.0, self._window_s)
        with self._lock:
            self._prune_unlocked(time.monotonic())
            self._recent[sk] = (exp, dict(result))

    def _prune_unlocked(self, now: float) -> None:
        dead = [k for k, (exp, _) in self._recent.items() if now > exp]
        for k in dead:
            self._recent.pop(k, None)
