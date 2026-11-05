"""Optional Redis-backed per-minute rate limiting with graceful in-memory fallback."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from rate_limiter import RateLimitResult, RateLimiter

logger = logging.getLogger("crm_mcp.redis_rl")


class RedisRateLimiter:
    """
    Fixed window per minute using bucket = int(time.time() // 60).
    Keys: rate:global:{b}, rate:user:{uid}:{b}, rate:workspace:{ws}:{b}
    """

    def __init__(
        self,
        redis: Any,
        *,
        user_limit: int,
        workspace_limit: int,
        global_limit: int,
    ) -> None:
        self._r = redis
        self._u = max(1, user_limit)
        self._w = max(1, workspace_limit)
        self._g = max(1, global_limit)

    async def check(self, *, user_id: str, workspace_id: str) -> RateLimitResult:
        bucket = int(time.time() // 60)
        expire_s = 120

        g_key = f"rate:global:{bucket}"
        gv = int(await self._r.incr(g_key))
        if gv == 1:
            await self._r.expire(g_key, expire_s)
        if gv > self._g:
            return RateLimitResult(False, 30.0)

        u_key = f"rate:user:{user_id}:{bucket}"
        uv = int(await self._r.incr(u_key))
        if uv == 1:
            await self._r.expire(u_key, expire_s)
        if uv > self._u:
            return RateLimitResult(False, 30.0)

        w_key = f"rate:workspace:{workspace_id}:{bucket}"
        wv = int(await self._r.incr(w_key))
        if wv == 1:
            await self._r.expire(w_key, expire_s)
        if wv > self._w:
            return RateLimitResult(False, 30.0)

        return RateLimitResult(True, 0.0)


def _halve_limits(settings: Any) -> tuple[tuple[int, str], tuple[int, str], tuple[int, str]]:
    def half(t: tuple[int, str]) -> tuple[int, str]:
        return (max(1, t[0] // 2), t[1])

    return half(settings.rate_limit_user), half(settings.rate_limit_workspace), half(settings.rate_limit_global)


async def create_async_limiter(settings: Any) -> Any:
    """Return RedisRateLimiter or in-memory RateLimiter (halved on degraded fallback)."""
    url = getattr(settings, "redis_url", None) or ""
    if not str(url).strip():
        return RateLimiter(
            user_limit=(settings.rate_limit_user[0], settings.rate_limit_user[1]),
            workspace_limit=(settings.rate_limit_workspace[0], settings.rate_limit_workspace[1]),
            global_limit=(settings.rate_limit_global[0], settings.rate_limit_global[1]),
        )
    try:
        from redis.asyncio import Redis

        client = Redis.from_url(
            str(url).strip(),
            encoding="utf-8",
            decode_responses=True,
        )
        await client.ping()
        logger.info("redis_rate_limiter: connected")
        return RedisRateLimiter(
            client,
            user_limit=settings.rate_limit_user[0],
            workspace_limit=settings.rate_limit_workspace[0],
            global_limit=settings.rate_limit_global[0],
        )
    except Exception as e:
        logger.warning("redis_rate_limiter: fallback to memory (%s)", e)
        u, w, g = _halve_limits(settings)
        logger.warning(
            json.dumps(
                {
                    "event": "rate_limiter_degraded",
                    "reason": str(e)[:200],
                    "limits_halved": True,
                }
            )
        )
        return RateLimiter(
            user_limit=u,
            workspace_limit=w,
            global_limit=g,
        )
