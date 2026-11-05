"""Environment-backed configuration. Fails fast when required values are missing."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Literal

Transport = Literal["stdio", "http"]


def _parse_rate_limit(value: str) -> tuple[int, str]:
    """Parse RATE_LIMIT like '60/min' or plain '60' (defaults to per-minute)."""
    value = (value or "").strip()
    if not value:
        return 60, "minute"
    m = re.match(r"^(\d+)\s*/\s*(minute|min|hour|hr|second|sec|s|m|h)$", value, re.I)
    if m:
        n = int(m.group(1))
        unit = m.group(2).lower()
        if unit in ("min", "minute", "m"):
            return n, "minute"
        if unit in ("hr", "hour", "h"):
            return n, "hour"
        if unit in ("sec", "second", "s"):
            return n, "second"
    if value.isdigit():
        return int(value), "minute"
    raise ValueError(f"Invalid rate limit expression: {value!r}")


@dataclass(frozen=True)
class Settings:
    crm_api_base_url: str
    jwt_secret: str
    jwt_algorithm: str
    mcp_transport: Transport
    mcp_port: int
    mcp_host: str
    redis_url: str | None
    tool_max_results: int
    cache_ttl_seconds: float
    rate_limit_user: tuple[int, str]
    rate_limit_workspace: tuple[int, str]
    rate_limit_global: tuple[int, str]
    httpx_timeout_s: float
    httpx_max_retries: int
    tool_timeout_s: float
    max_json_payload_bytes: int
    max_search_string_len: int
    dry_run: bool
    circuit_threshold: int
    circuit_window_s: float
    circuit_cooldown_s: float
    write_guard_dedupe_window_s: float
    audit_mcp_tool_calls: bool
    reject_identity_tool_args: bool


def load_settings() -> Settings:
    base = os.environ.get("CRM_API_BASE_URL", "").rstrip("/")
    if not base:
        raise RuntimeError("CRM_API_BASE_URL is required")

    jwt_secret = os.environ.get("JWT_SECRET") or os.environ.get("JWT_SECRET_KEY")
    if not jwt_secret:
        raise RuntimeError("JWT_SECRET (or JWT_SECRET_KEY) is required")

    transport_raw = os.environ.get("MCP_TRANSPORT", "stdio").strip().lower()
    if transport_raw not in ("stdio", "http"):
        raise RuntimeError("MCP_TRANSPORT must be stdio or http")
    transport: Transport = transport_raw  # type: ignore[assignment]

    port = int(os.environ.get("MCP_PORT", "3100"))
    host = os.environ.get("MCP_HOST", "0.0.0.0")

    tool_max = int(os.environ.get("TOOL_MAX_RESULTS", "50"))
    cache_ttl = float(os.environ.get("CACHE_TTL_SECONDS", "10"))

    rl_u = _parse_rate_limit(os.environ.get("RATE_LIMIT_PER_USER", "60/min"))
    rl_w = _parse_rate_limit(os.environ.get("RATE_LIMIT_PER_WORKSPACE", "300/min"))
    rl_g = _parse_rate_limit(os.environ.get("RATE_LIMIT_GLOBAL", "1000/min"))

    redis_url = (os.environ.get("REDIS_URL") or "").strip() or None

    return Settings(
        crm_api_base_url=base,
        jwt_secret=jwt_secret,
        jwt_algorithm=os.environ.get("JWT_ALGORITHM", "HS256"),
        mcp_transport=transport,
        mcp_port=port,
        mcp_host=host,
        redis_url=redis_url,
        tool_max_results=tool_max,
        cache_ttl_seconds=cache_ttl,
        rate_limit_user=rl_u,
        rate_limit_workspace=rl_w,
        rate_limit_global=rl_g,
        httpx_timeout_s=float(os.environ.get("HTTPX_TIMEOUT_SECONDS", "10")),
        httpx_max_retries=int(os.environ.get("HTTPX_MAX_RETRIES", "2")),
        tool_timeout_s=float(os.environ.get("TOOL_TIMEOUT_SECONDS", "12")),
        max_json_payload_bytes=int(os.environ.get("MAX_JSON_PAYLOAD_BYTES", "65536")),
        max_search_string_len=int(os.environ.get("MAX_SEARCH_STRING_LEN", "512")),
        dry_run=os.environ.get("DRY_RUN", "").strip().lower() in ("1", "true", "yes"),
        circuit_threshold=int(os.environ.get("CIRCUIT_FAILURE_THRESHOLD", "5")),
        circuit_window_s=float(os.environ.get("CIRCUIT_WINDOW_SECONDS", "30")),
        circuit_cooldown_s=float(os.environ.get("CIRCUIT_COOLDOWN_SECONDS", "30")),
        write_guard_dedupe_window_s=float(
            os.environ.get("WRITE_GUARD_DEDUPE_WINDOW_SECONDS", "8")
        ),
        audit_mcp_tool_calls=os.environ.get("MCP_AUDIT_TOOL_CALLS", "true").strip().lower()
        not in ("0", "false", "no", "off"),
        reject_identity_tool_args=os.environ.get("MCP_REJECT_IDENTITY_ARGS", "true").strip().lower()
        not in ("0", "false", "no", "off"),
    )
