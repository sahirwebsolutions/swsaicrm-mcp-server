"""Starlette ASGI app for remote MCP clients.

- ``/mcp``: Streamable HTTP, stateless, so any worker or replica can serve any request.
- ``/mcp/events`` + ``/mcp/post/``: legacy SSE for older clients.
- OAuth discovery (RFC 9728 + RFC 8414) and dynamic client registration (RFC 7591),
  so assistants can sign in with the CRM approval page instead of a pasted token.
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import time
from contextlib import asynccontextmanager
from typing import Any, Callable
from urllib.parse import urlparse

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.types import ASGIApp, Receive, Scope, Send

from context_state import bearer_header_var
from crm_sse import CrmSseServerTransport
from mcp.server.lowlevel import Server
from mcp.server.models import InitializationOptions
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

SCOPE = "crm"
_MAX_REGISTER_BYTES = 16_384
_log = logging.getLogger("crm_mcp.http")


def _public_base(request: Request) -> str:
    configured = (os.environ.get("MCP_PUBLIC_URL") or "").strip().rstrip("/")
    for suffix in ("/mcp/events", "/mcp"):
        if configured.endswith(suffix):
            configured = configured[: -len(suffix)]
    if configured:
        return configured
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    return f"{proto}://{host}"


def _redirect_allowed(uri: str) -> bool:
    parsed = urlparse((uri or "").strip())
    host = (parsed.hostname or "").lower()
    if parsed.scheme == "https" and host:
        return True
    return parsed.scheme == "http" and host in {"localhost", "127.0.0.1"}


def _client_slug(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9 ._-]+", "", (name or "").strip())[:60].strip()
    return slug or "Assistant"


def build_starlette_app(
    mcp_server: Server,
    init_options: InitializationOptions,
    crm_client: object | None = None,
    token_is_valid: Callable[[str], bool] | None = None,
) -> Starlette:
    message_mount = "/mcp/post/"
    sse = CrmSseServerTransport(message_mount)
    session_manager = StreamableHTTPSessionManager(app=mcp_server, stateless=True, json_response=True)

    class _ResponseAlreadySent(Response):
        """SSE already wrote the ASGI response through request._send."""

        async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
            return

    class BearerCaptureMiddleware:
        """Read Authorization without buffering streamed bodies."""

        def __init__(self, app: ASGIApp) -> None:
            self.app = app

        async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
            if scope["type"] != "http":
                await self.app(scope, receive, send)
                return
            auth = None
            for key, value in scope.get("headers") or []:
                if key == b"authorization":
                    auth = value.decode("latin1")
                    break
            token = bearer_header_var.set(auth)
            try:
                await self.app(scope, receive, send)
            finally:
                bearer_header_var.reset(token)

    def _challenge(request: Request, description: str) -> Response:
        base = _public_base(request)
        header = (
            f'Bearer realm="crm", error="invalid_token", error_description="{description}", '
            f'resource_metadata="{base}/.well-known/oauth-protected-resource", scope="{SCOPE}"'
        )
        return JSONResponse(
            {"error": "invalid_token", "error_description": description},
            status_code=401,
            headers={"WWW-Authenticate": header},
        )

    class StreamableEndpoint:
        """``/mcp``: reject missing or bad tokens with an OAuth challenge, then serve MCP."""

        async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
            request = Request(scope, receive)
            raw = (request.headers.get("authorization") or "").strip()
            token = raw[7:].strip() if raw[:7].lower() == "bearer " else ""
            if not token:
                await _challenge(request, "Sign in to the CRM to continue")(scope, receive, send)
                return
            if token_is_valid is not None and not token_is_valid(token):
                await _challenge(request, "This connection expired or was revoked")(scope, receive, send)
                return
            await session_manager.handle_request(*_observed(scope, receive, send))

    def _observed(scope: Scope, receive: Receive, send: Send) -> tuple[Scope, Receive, Send]:
        """Log the JSON-RPC method and any rejected request, without credentials or arguments."""
        seen: dict[str, Any] = {"rpc": None, "status": None, "error": b""}
        headers = dict(scope.get("headers") or [])

        async def recv() -> Any:
            message = await receive()
            if message.get("type") == "http.request" and seen["rpc"] is None:
                found = re.search(rb'"method"\s*:\s*"([^"]{1,80})"', message.get("body") or b"")
                seen["rpc"] = found.group(1).decode() if found else "-"
            return message

        async def snd(message: Any) -> None:
            if message.get("type") == "http.response.start":
                seen["status"] = message.get("status")
            elif message.get("type") == "http.response.body" and (seen["status"] or 0) >= 400:
                seen["error"] += (message.get("body") or b"")[:300]
            await send(message)
            if message.get("type") == "http.response.body" and not message.get("more_body"):
                _log.info(
                    json.dumps(
                        {
                            "event": "mcp_http",
                            "http_method": scope.get("method"),
                            "rpc": seen["rpc"],
                            "status": seen["status"],
                            "protocol": headers.get(b"mcp-protocol-version", b"").decode("latin1")[:40],
                            "client": headers.get(b"user-agent", b"").decode("latin1")[:60],
                            "error": seen["error"].decode("utf-8", "replace")[:300] or None,
                        }
                    )
                )

        return scope, recv, snd

    async def handle_sse(request: Request) -> Response:
        async with sse.connect_sse(
            request.scope,
            request.receive,
            request._send,  # type: ignore[attr-defined]
        ) as streams:
            await mcp_server.run(streams[0], streams[1], init_options)
        return _ResponseAlreadySent()

    async def protected_resource(request: Request) -> JSONResponse:
        base = _public_base(request)
        return JSONResponse(
            {
                "resource": f"{base}/mcp",
                "authorization_servers": [base],
                "bearer_methods_supported": ["header"],
                "scopes_supported": [SCOPE],
                "resource_name": "SWS CRM",
            }
        )

    async def authorization_server(request: Request) -> JSONResponse:
        base = _public_base(request)
        api = (os.environ.get("CRM_API_BASE_URL") or "").rstrip("/")
        app_url = (os.environ.get("CRM_APP_URL") or os.environ.get("APP_URL") or "").rstrip("/")
        return JSONResponse(
            {
                "issuer": base,
                "authorization_endpoint": f"{app_url}/settings/api-access" if app_url else "",
                "token_endpoint": f"{api}/api/v1/api-access/oauth/token" if api else "",
                "registration_endpoint": f"{base}/register",
                "scopes_supported": [SCOPE],
                "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code"],
                "token_endpoint_auth_methods_supported": ["none"],
                "code_challenge_methods_supported": ["S256"],
            }
        )

    async def register(request: Request) -> JSONResponse:
        raw = await request.body()
        if len(raw) > _MAX_REGISTER_BYTES:
            return JSONResponse({"error": "invalid_client_metadata", "error_description": "Too large"}, status_code=400)
        try:
            meta: Any = json.loads(raw or b"{}")
        except ValueError:
            meta = None
        if not isinstance(meta, dict):
            return JSONResponse({"error": "invalid_client_metadata", "error_description": "Send JSON"}, status_code=400)
        uris = meta.get("redirect_uris")
        if not isinstance(uris, list) or not uris or not all(isinstance(u, str) and _redirect_allowed(u) for u in uris):
            return JSONResponse(
                {"error": "invalid_redirect_uri", "error_description": "Use https, or http on localhost"},
                status_code=400,
            )
        name = _client_slug(str(meta.get("client_name") or ""))
        return JSONResponse(
            {
                "client_id": f"{name}~{secrets.token_urlsafe(9)}",
                "client_id_issued_at": int(time.time()),
                "client_name": name,
                "redirect_uris": uris,
                "grant_types": ["authorization_code"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
                "scope": SCOPE,
            },
            status_code=201,
            headers={"Cache-Control": "no-store"},
        )

    async def health(_request: Request) -> JSONResponse:
        return JSONResponse({"ok": True})

    routes = [
        Route("/healthz", endpoint=health, methods=["GET"]),
        Route("/.well-known/oauth-protected-resource", endpoint=protected_resource, methods=["GET"]),
        Route("/.well-known/oauth-protected-resource/mcp", endpoint=protected_resource, methods=["GET"]),
        Route("/.well-known/oauth-authorization-server", endpoint=authorization_server, methods=["GET"]),
        Route("/.well-known/oauth-authorization-server/mcp", endpoint=authorization_server, methods=["GET"]),
        Route("/register", endpoint=register, methods=["POST"]),
        Route("/mcp", endpoint=StreamableEndpoint(), methods=["GET", "POST", "DELETE"]),
        Route("/mcp/events", endpoint=handle_sse, methods=["GET"]),
        Mount(message_mount, app=sse.handle_post_message),
    ]

    @asynccontextmanager
    async def lifespan(_app: Starlette):
        async with session_manager.run():
            yield
        if crm_client is not None and hasattr(crm_client, "aclose"):
            await crm_client.aclose()  # type: ignore[misc]

    app = Starlette(
        routes=routes,
        middleware=[Middleware(BearerCaptureMiddleware)],
        lifespan=lifespan,
    )
    if crm_client is not None:
        app.state.crm_client = crm_client
    return app
