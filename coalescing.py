"""Request coalescing for identical in-flight tool executions (memory-safe)."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

logger = logging.getLogger("crm_mcp.coalesce")

T = TypeVar("T")

_COALESCE_TASK_TIMEOUT_S = 120.0


class RequestCoalescer:
    def __init__(self, task_timeout_s: float = _COALESCE_TASK_TIMEOUT_S) -> None:
        self._lock = asyncio.Lock()
        self._inflight: dict[str, asyncio.Task] = {}
        self._task_timeout_s = task_timeout_s

    async def run(
        self,
        key: str,
        factory: Callable[[], Awaitable[T]],
    ) -> T:
        async with self._lock:
            existing = self._inflight.get(key)
            if existing is not None and not existing.done():
                task = existing
                logger.debug("coalesce_join key=%s", key[:64])
            else:

                async def _work() -> T:
                    try:
                        return await factory()
                    finally:
                        async with self._lock:
                            cur = self._inflight.get(key)
                            t_self = asyncio.current_task()
                            if cur is not None and cur is t_self:
                                self._inflight.pop(key, None)

                task = asyncio.create_task(_work())
                self._inflight[key] = task

        try:
            return await asyncio.wait_for(task, timeout=self._task_timeout_s)
        except asyncio.TimeoutError:
            logger.warning(json.dumps({"event": "coalesce_timeout", "key_prefix": key[:48]}))
            async with self._lock:
                self._inflight.pop(key, None)
            raise
