"""
CRM MCP adapter — thin layer over FastAPI. Run with stdio (Cursor) or HTTP (SSE).

`python main.py` with cwd on PYTHONPATH (see README).
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import mcp.types as types
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.stdio import stdio_server

from access_gate import allowed_tools
from auth import AuthError, decode_bearer_jwt
from cache import TtlCache
from canonical import canonical_json
from client import CRMClient, UpstreamError
from coalescing import RequestCoalescer
from config import Settings, load_settings
from context_state import resolve_raw_bearer_token
from circuit_breaker import EndpointCircuitBreaker
from http_app import build_starlette_app
from input_normalize import normalize_raw_params
from middleware import ToolContext
from write_guard import WriteGuard
from redis_rate_limiter import create_async_limiter
from tools import load_tool_classes, mcp_tool_definitions, tool_registry
from tools.base import BaseTool
from tracing import new_request_id
from scope_guard import forbidden_identity_argument, is_identity_key
from tool_logging import log_mcp_tool_audit, params_fingerprint

logger = logging.getLogger("crm_mcp")


def _configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")


def _strip_identity_overrides(arguments: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in arguments.items() if not is_identity_key(str(k))}


@dataclass
class Runtime:
    settings: Settings
    server: Server
    init_options: Any
    registry: dict[str, type[BaseTool]]
    client: CRMClient
    cache: TtlCache
    limiter: object
    coalescer: RequestCoalescer
    write_guard: WriteGuard


def _build_server_and_handlers(
    settings: Settings,
    classes: list[type[BaseTool]],
    registry: dict[str, type[BaseTool]],
    client: CRMClient,
    cache: TtlCache,
    limiter: object,
    coalescer: RequestCoalescer,
    write_guard: WriteGuard,
) -> tuple[Server, Any]:
    server = Server("crm-mcp", version="1.0.0")

    @server.list_tools()
    async def _list_tools() -> list[types.Tool]:
        raw = resolve_raw_bearer_token()
        if not raw:
            return []
        try:
            auth = decode_bearer_jwt(
                raw,
                secret=settings.jwt_secret,
                algorithms=[settings.jwt_algorithm],
            )
        except AuthError:
            return []
        names, _reason = await allowed_tools(client, cache, auth)
        visible = [cls for cls in classes if cls.name in names]
        return mcp_tool_definitions(visible)

    @server.call_tool()
    async def _handle_tool(name: str, arguments: dict[str, Any] | None) -> Any:
        rid = new_request_id()
        raw_args = _strip_identity_overrides(arguments or {})
        norm_args = normalize_raw_params(name, raw_args)
        fp = params_fingerprint(norm_args)
        uid: str | None = None
        wid: str | None = None

        def audit(outcome: str) -> None:
            if settings.audit_mcp_tool_calls:
                log_mcp_tool_audit(
                    logger,
                    tool=name,
                    request_id=rid,
                    outcome=outcome,
                    params_fp=fp,
                    user_id=uid,
                    workspace_id=wid,
                )

        raw = resolve_raw_bearer_token()
        if not raw:
            audit("auth_failed")
            return {
                "error": "auth_failed",
                "message": "Missing Authorization bearer token (HTTP) or MCP_BEARER_TOKEN (stdio)",
            }

        try:
            auth = decode_bearer_jwt(
                raw,
                secret=settings.jwt_secret,
                algorithms=[settings.jwt_algorithm],
            )
        except AuthError as e:
            audit("auth_failed")
            return {"error": e.code, "message": e.message}

        uid, wid = auth.user_id, auth.workspace_id

        rl = await limiter.check(user_id=auth.user_id, workspace_id=auth.workspace_id)
        if not rl.ok:
            audit("rate_limited")
            return {
                "error": "rate_limited",
                "retry_after": max(1, int(math.ceil(rl.retry_after_s))),
            }

        tool_cls = registry.get(name)
        if not tool_cls:
            audit("unknown_tool")
            return {"error": "invalid_params", "message": f"Unknown tool: {name}"}

        allowed, deny_reason = await allowed_tools(client, cache, auth)
        if name not in allowed:
            audit("permission_denied")
            return {
                "error": "permission_denied",
                "message": deny_reason or "Your role cannot use this action",
            }

        if settings.reject_identity_tool_args:
            bad_key = forbidden_identity_argument(norm_args)
            if bad_key:
                audit("identity_args_rejected")
                return {
                    "error": "invalid_params",
                    "message": f"Tool arguments must not include identity or tenancy overrides ({bad_key})",
                }

        tool = tool_cls()
        ctx = ToolContext(
            settings=settings,
            auth=auth,
            client=client,
            cache=cache,
            rate_limiter=limiter,
            request_id=rid,
            coalescer=coalescer,
            write_guard=write_guard,
        )

        ckey = f"{auth.workspace_id}:{name}:{canonical_json(norm_args)}"

        async def _execute() -> Any:
            return await tool.run(ctx, norm_args)

        t0 = time.perf_counter()
        try:
            result = await asyncio.wait_for(
                coalescer.run(ckey, _execute),
                timeout=settings.tool_timeout_s,
            )
            latency_ms = (time.perf_counter() - t0) * 1000
            tool.log_event(
                "success",
                workspace_id=auth.workspace_id,
                user_id=auth.user_id,
                request_id=rid,
                latency_ms=latency_ms,
                tool=name,
            )
            audit("success")
            return result
        except asyncio.TimeoutError:
            logger.warning(json.dumps({"event": "tool_timeout", "tool": name, "request_id": rid}))
            audit("timeout")
            return {"error": "timeout", "tool": name}
        except UpstreamError as u:
            latency_ms = (time.perf_counter() - t0) * 1000
            tool.log_event(
                "error",
                workspace_id=auth.workspace_id,
                user_id=auth.user_id,
                request_id=rid,
                latency_ms=latency_ms,
                tool=name,
            )
            audit("upstream_error")
            return {
                "error": u.code,
                "message": u.message,
                "http_status": u.status,
            }
        except ValueError as ve:
            audit("invalid_params")
            return {"error": "invalid_params", "message": str(ve)}
        except Exception:
            logger.exception("tool_failure")
            audit("internal_error")
            return {"error": "upstream_error", "message": "internal error"}

    init_options = server.create_initialization_options(
        notification_options=NotificationOptions(),
    )
    return server, init_options


async def build_runtime_async() -> Runtime:
    settings = load_settings()
    classes = load_tool_classes()
    registry = tool_registry(classes)
    limiter = await create_async_limiter(settings)
    circuit = EndpointCircuitBreaker(
        threshold=settings.circuit_threshold,
        window_s=settings.circuit_window_s,
        cooldown_s=settings.circuit_cooldown_s,
    )
    client = CRMClient(
        settings.crm_api_base_url,
        timeout_s=settings.httpx_timeout_s,
        max_retries=settings.httpx_max_retries,
        circuit=circuit,
    )
    cache = TtlCache(settings.cache_ttl_seconds)
    coalescer = RequestCoalescer()
    write_guard = WriteGuard(settings.write_guard_dedupe_window_s)
    server, init_options = _build_server_and_handlers(
        settings, classes, registry, client, cache, limiter, coalescer, write_guard
    )
    return Runtime(
        settings=settings,
        server=server,
        init_options=init_options,
        registry=registry,
        client=client,
        cache=cache,
        limiter=limiter,
        coalescer=coalescer,
        write_guard=write_guard,
    )


async def _run_stdio() -> None:
    rt = await build_runtime_async()
    try:
        async with stdio_server() as streams:
            await rt.server.run(
                streams[0],
                streams[1],
                rt.init_options,
            )
    finally:
        await rt.client.aclose()


async def _run_http_async() -> None:
    import uvicorn

    rt = await build_runtime_async()
    app = build_starlette_app(rt.server, rt.init_options, crm_client=rt.client)
    cfg = uvicorn.Config(
        app,
        host=rt.settings.mcp_host,
        port=rt.settings.mcp_port,
        log_level="info",
    )
    server = uvicorn.Server(cfg)
    await server.serve()


def main() -> None:
    _configure_logging()
    settings = load_settings()
    if settings.mcp_transport == "stdio":
        asyncio.run(_run_stdio())
    else:
        asyncio.run(_run_http_async())


if __name__ == "__main__":
    main()
