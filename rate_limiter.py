"""Multi-layer sliding-window rate limits (in-memory)."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Literal

WindowUnit = Literal["second", "minute", "hour"]


@dataclass
class RateLimitResult:
    ok: bool
    retry_after_s: float


def window_seconds(unit: str) -> float:
    u = unit.lower()
    if u in ("second", "sec", "s"):
        return 1.0
    if u in ("minute", "min", "m"):
        return 60.0
    if u in ("hour", "hr", "h"):
        return 3600.0
    return 60.0


class SlidingCounter:
    """Single leaky bucket (fixed window)."""

    def __init__(self, max_events: int, window_s: float) -> None:
        self._max = max(1, max_events)
        self._window = max(0.5, window_s)
        self._lock = asyncio.Lock()
        self._window_start = time.monotonic()
        self._count = 0

    async def check(self) -> RateLimitResult:
        async with self._lock:
            now = time.monotonic()
            if now - self._window_start >= self._window:
                self._window_start = now
                self._count = 0
            if self._count >= self._max:
                retry = self._window - (now - self._window_start)
                return RateLimitResult(False, max(0.1, retry))
            self._count += 1
            return RateLimitResult(True, 0.0)


class KeyedRateLayer:
    """One counter per key (user_id or workspace_id)."""

    def __init__(
        self,
        max_keys: int,
        limit: tuple[int, str],
    ) -> None:
        self._max_keys = max(1024, max_keys)
        self._n, unit = limit
        self._ws = window_seconds(unit)
        self._counters: dict[str, SlidingCounter] = {}
        self._order: list[str] = []
        self._lock = asyncio.Lock()

    async def check(self, key: str) -> RateLimitResult:
        async with self._lock:
            if key not in self._counters:
                if len(self._counters) >= self._max_keys:
                    # drop oldest to bound memory
                    oldest = self._order.pop(0)
                    self._counters.pop(oldest, None)
                self._counters[key] = SlidingCounter(self._n, self._ws)
                self._order.append(key)
        return await self._counters[key].check()


class RateLimiter:
    """Global + per-user + per-workspace."""

    def __init__(
        self,
        user_limit: tuple[int, str],
        workspace_limit: tuple[int, str],
        global_limit: tuple[int, str],
    ) -> None:
        g_n, g_u = global_limit
        self._global = SlidingCounter(g_n, window_seconds(g_u))
        self._users = KeyedRateLayer(max_keys=50_000, limit=user_limit)
        self._workspaces = KeyedRateLayer(max_keys=20_000, limit=workspace_limit)

    async def check(self, *, user_id: str, workspace_id: str) -> RateLimitResult:
        g = await self._global.check()
        if not g.ok:
            return RateLimitResult(False, g.retry_after_s)
        u = await self._users.check(user_id)
        if not u.ok:
            return RateLimitResult(False, u.retry_after_s)
        w = await self._workspaces.check(workspace_id)
        if not w.ok:
            return RateLimitResult(False, w.retry_after_s)
        return RateLimitResult(True, 0.0)


def build_rate_limiter_from_settings(settings) -> RateLimiter:
    return RateLimiter(
        user_limit=(settings.rate_limit_user[0], settings.rate_limit_user[1]),
        workspace_limit=(settings.rate_limit_workspace[0], settings.rate_limit_workspace[1]),
        global_limit=(settings.rate_limit_global[0], settings.rate_limit_global[1]),
    )
