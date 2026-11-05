"""Per-endpoint circuit breaker: CLOSED → OPEN → HALF_OPEN → CLOSED."""

from __future__ import annotations

import time
from collections import deque
from enum import Enum
from typing import Deque


class CircuitOpen(Exception):
    pass


class _State(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class EndpointCircuitBreaker:
    """
    - CLOSED: failures >= threshold within window → OPEN
    - OPEN: reject until cooldown → HALF_OPEN
    - HALF_OPEN: next success closes; failure → OPEN
    """

    def __init__(
        self,
        *,
        threshold: int = 5,
        window_s: float = 30.0,
        cooldown_s: float = 30.0,
        half_open_success_target: int = 1,
    ) -> None:
        self._threshold = max(1, threshold)
        self._window_s = window_s
        self._cooldown_s = cooldown_s
        self._half_open_success_target = max(1, half_open_success_target)
        self._fail_times: dict[str, Deque[float]] = {}
        self._state: dict[str, _State] = {}
        self._open_until: dict[str, float] = {}
        self._half_open_successes: dict[str, int] = {}

    @staticmethod
    def key(method: str, path: str, workspace_id: str | None = None) -> str:
        base = f"{method.upper().strip()}:{path}"
        if workspace_id:
            return f"{base}:{workspace_id}"
        return base

    def check_before_request(self, key: str) -> None:
        now = time.monotonic()
        st = self._state.get(key, _State.CLOSED)
        if st == _State.OPEN:
            until = self._open_until.get(key, 0)
            if now < until:
                raise CircuitOpen()
            self._state[key] = _State.HALF_OPEN
            self._half_open_successes[key] = 0
            self._open_until.pop(key, None)
            return
        if st == _State.HALF_OPEN:
            return

    def record_success(self, key: str) -> None:
        st = self._state.get(key, _State.CLOSED)
        if st == _State.HALF_OPEN:
            self._half_open_successes[key] = self._half_open_successes.get(key, 0) + 1
            if self._half_open_successes[key] >= self._half_open_success_target:
                self._state[key] = _State.CLOSED
                self._fail_times.pop(key, None)
                self._half_open_successes.pop(key, None)
            return
        self._fail_times.pop(key, None)
        self._state.pop(key, None)
        self._half_open_successes.pop(key, None)
        self._open_until.pop(key, None)

    def record_failure(self, key: str) -> None:
        now = time.monotonic()
        st = self._state.get(key, _State.CLOSED)

        if st == _State.HALF_OPEN:
            self._state[key] = _State.OPEN
            self._open_until[key] = now + self._cooldown_s
            self._half_open_successes.pop(key, None)
            return

        dq = self._fail_times.setdefault(key, deque())
        dq.append(now)
        while dq and now - dq[0] > self._window_s:
            dq.popleft()
        if len(dq) >= self._threshold:
            self._state[key] = _State.OPEN
            self._open_until[key] = now + self._cooldown_s
