"""Starlette ASGI app: GET /mcp/events (SSE) + POST message mount (library contract)."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route

from context_state import bearer_header_var
from crm_sse import CrmSseServerTransport
from mcp.server.models import InitializationOptions
from mcp.server.lowlevel import Server


def build_starlette_app(
    mcp_server: Server,
    init_options: InitializationOptions,
    crm_client: object | None = None,
) -> Starlette:
    """
    SSE GET path: `/mcp/events`. Client POST URL comes from SSE `endpoint` event
    (typically `/mcp/post/?session_id=...` when message mount is `/mcp/post/`).
    """

    message_mount = "/mcp/post/"
    sse = CrmSseServerTransport(message_mount)

    class BearerCaptureMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
            auth = request.headers.get("authorization")
            tok = bearer_header_var.set(auth)
            try:
                return await call_next(request)
            finally:
                bearer_header_var.reset(tok)

    async def handle_sse(request: Request) -> Response:
        async with sse.connect_sse(
            request.scope,
            request.receive,
            request._send,  # type: ignore[attr-defined]
        ) as streams:
            await mcp_server.run(
                streams[0],
                streams[1],
                init_options,
            )
        return Response()

    async def oauth_metadata(_request: Request) -> JSONResponse:
        api = (os.environ.get("CRM_API_BASE_URL") or "").rstrip("/")
        app_url = (os.environ.get("CRM_APP_URL") or os.environ.get("APP_URL") or "").rstrip("/")
        return JSONResponse(
            {
                "issuer": api,
                "authorization_endpoint": f"{app_url}/settings/api-access" if app_url else "",
                "token_endpoint": f"{api}/api/v1/api-access/oauth/token" if api else "",
                "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code"],
                "token_endpoint_auth_methods_supported": ["none"],
                "code_challenge_methods_supported": ["S256"],
            }
        )

    routes = [
        Route("/.well-known/oauth-authorization-server", endpoint=oauth_metadata, methods=["GET"]),
        Route("/mcp/events", endpoint=handle_sse, methods=["GET"]),
        Mount(
            "/mcp/post/",
            app=sse.handle_post_message,
        ),
    ]

    @asynccontextmanager
    async def lifespan(_app: Starlette):
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
