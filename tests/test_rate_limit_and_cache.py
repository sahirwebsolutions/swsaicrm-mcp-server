import pytest

from cache import TtlCache
from rate_limiter import RateLimiter, SlidingCounter


@pytest.mark.asyncio
async def test_sliding_counter_limit():
    c = SlidingCounter(2, window_s=60.0)
    assert (await c.check()).ok
    assert (await c.check()).ok
    r = await c.check()
    assert not r.ok
    assert r.retry_after_s > 0


@pytest.mark.asyncio
async def test_rate_limiter_layers():
    rl = RateLimiter(
        user_limit=(5, "minute"),
        workspace_limit=(5, "minute"),
        global_limit=(100, "minute"),
    )
    for i in range(5):
        assert (await rl.check(user_id="u1", workspace_id="w1")).ok
    r = await rl.check(user_id="u1", workspace_id="w1")
    assert not r.ok


def test_cache_ttl_expires(monkeypatch):
    import time as _t

    class FakeTime:
        now = 0.0

        @classmethod
        def monotonic(cls):
            return cls.now

    monkeypatch.setattr("cache.time.monotonic", FakeTime.monotonic)
    c = TtlCache(10.0)
    c.set("k", {"a": 1})
    FakeTime.now = 100.0
    assert c.get("k") is None
