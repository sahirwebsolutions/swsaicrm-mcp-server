"""Execution context passed into tools (auth + request metadata)."""

from __future__ import annotations

from dataclasses import dataclass

from auth import AuthContext
from client import CRMClient
from config import Settings
from cache import TtlCache
from coalescing import RequestCoalescer
from write_guard import WriteGuard


@dataclass
class ToolContext:
    settings: Settings
    auth: AuthContext
    client: CRMClient
    cache: TtlCache
    rate_limiter: object
    request_id: str
    coalescer: RequestCoalescer
    write_guard: WriteGuard
