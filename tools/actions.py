"""Every published CRM action, reachable through four tools.

The CRM publishes its FastAPI routes per role (``/api/v1/api-access/actions``).
The assistant searches them, reads one action's inputs, then calls it. The CRM
checks the role, the workspace, and the route's own rules on every call.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, ClassVar, Literal
from urllib.parse import quote

from pydantic import BaseModel, Field

from client import UpstreamError
from idempotency_keys import compute_idempotency_key
from middleware import ToolContext
from response_shape import DEFAULT_MAX_CHARS, HARD_MAX_CHARS, fit
from tool_logging import log_write_tool_invoked
from tools.base import BaseTool, ToolExecuteContext, validate_args

_PARAM = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)(?::[a-z]+)?\}")
_DESCRIBE_TTL_S = 600.0
_WRITE_METHODS = ("POST", "PUT", "PATCH", "DELETE")

Scalar = str | int | float | bool


class SearchActionsParams(BaseModel):
    model_config = {"extra": "forbid"}

    query: str = Field(..., min_length=1, max_length=300, description="What you want to do, in plain words")
    kind: Literal["read", "create", "edit", "delete", "send"] | None = None
    limit: int = Field(12, ge=1, le=30)


class DescribeActionParams(BaseModel):
    model_config = {"extra": "forbid"}

    action: str = Field(..., min_length=5, max_length=300, description="Action id from search_actions, e.g. 'PUT /api/v1/tasks/{task_id}'")


class CallReadActionParams(BaseModel):
    model_config = {"extra": "forbid"}

    action: str = Field(..., min_length=5, max_length=300, description="A GET action id from search_actions")
    path_params: dict[str, Scalar] = Field(default_factory=dict)
    query: dict[str, Scalar | list[Scalar] | None] = Field(default_factory=dict)
    max_chars: int = Field(DEFAULT_MAX_CHARS, ge=2_000, le=HARD_MAX_CHARS)


class CallWriteActionParams(BaseModel):
    model_config = {"extra": "forbid"}

    action: str = Field(..., min_length=5, max_length=300, description="A POST, PUT, PATCH, or DELETE action id")
    path_params: dict[str, Scalar] = Field(default_factory=dict)
    query: dict[str, Scalar | list[Scalar] | None] = Field(default_factory=dict)
    body: dict[str, Any] | list[Any] | None = None
    idempotency_key: str | None = Field(None, min_length=8, max_length=128)
    max_chars: int = Field(DEFAULT_MAX_CHARS, ge=2_000, le=HARD_MAX_CHARS)


def split_action(action: str) -> tuple[str, str]:
    method, _, path = " ".join(str(action or "").split()).partition(" ")
    method = method.upper()
    if not method or not path.startswith("/api/"):
        raise ValueError("Use an action id from search_actions, e.g. 'GET /api/v1/tasks/'")
    if ".." in path or "?" in path or "#" in path:
        raise ValueError("Action paths cannot contain '..', '?', or '#'")
    return method, path


def fill_path(template: str, values: dict[str, Any], workspace_id: str) -> str:
    missing: list[str] = []

    def repl(match: re.Match[str]) -> str:
        name = match.group(1)
        if name == "workspace_id":
            return quote(workspace_id, safe="")
        if name not in values or values[name] in (None, ""):
            missing.append(name)
            return match.group(0)
        return quote(str(values[name]), safe="")

    path = _PARAM.sub(repl, template)
    if missing:
        raise ValueError(f"Missing path_params: {', '.join(missing)}")
    return path


def _clean_query(query: dict[str, Any], workspace_id: str) -> dict[str, Any]:
    out = {k: v for k, v in query.items() if v is not None and str(k).lower() != "workspace_id"}
    out["workspace_id"] = workspace_id
    return out


def _meta(ctx: ToolContext) -> ToolExecuteContext:
    return ToolExecuteContext(user_id=ctx.auth.user_id, workspace_id=ctx.auth.workspace_id, request_id=ctx.request_id)


def _token_key(ctx: ToolContext, kind: str, part: str) -> str:
    digest = hashlib.sha256(ctx.auth.token.encode("utf-8")).hexdigest()[:24]
    return f"actions:{kind}:{digest}:{part}"


async def describe_cached(ctx: ToolContext, action: str) -> dict[str, Any]:
    key = _token_key(ctx, "describe", action)
    hit = ctx.cache.get(key)
    if isinstance(hit, dict):
        return hit
    resp = await ctx.client._request_with_retries(
        "GET",
        "/api/v1/api-access/actions/describe",
        auth=ctx.auth,
        params={"workspace_id": ctx.auth.workspace_id, "action": action},
    )
    body = ctx.client.raise_for_status(resp)
    ctx.cache.set(key, body, ttl_s=_DESCRIBE_TTL_S)
    return body


async def resolve_action(ctx: ToolContext, method: str, path: str) -> tuple[str, dict[str, Any]]:
    """Return the published path template and its description, tolerating a trailing-slash mismatch."""
    try:
        described = await describe_cached(ctx, f"{method} {path}")
    except UpstreamError as exc:
        if exc.code != "not_found":
            raise
        alt = path[:-1] if path.endswith("/") else f"{path}/"
        described = await describe_cached(ctx, f"{method} {alt}")
    _, canonical = split_action(str(described.get("action") or f"{method} {path}"))
    return canonical, described


class SearchActionsTool(BaseTool):
    name: ClassVar[str] = "search_actions"
    read_only: ClassVar[bool | None] = True
    description: ClassVar[str] = (
        "Find any CRM action your role allows, beyond the dedicated tools: comments, subtasks, "
        "time tracking, meetings, projects, documents, sales, campaigns, reports, and more. "
        "Describe the goal in plain words (e.g. 'add comment to task', 'project milestones'). "
        "Returns action ids; pass one to describe_action, then call_read_action or call_write_action."
    )

    @classmethod
    def input_schema(cls) -> dict[str, Any]:
        return SearchActionsParams.model_json_schema()

    async def run(self, ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
        p = validate_args(params, SearchActionsParams)
        q: dict[str, Any] = {"workspace_id": ctx.auth.workspace_id, "q": p.query, "limit": p.limit}
        if p.kind:
            q["kind"] = p.kind
        key = _token_key(ctx, "search", f"{p.kind}:{p.limit}:{p.query.lower().strip()}")
        hit = ctx.cache.get(key)
        if hit is not None:
            return hit
        resp = await ctx.client._request_with_retries("GET", "/api/v1/api-access/actions", auth=ctx.auth, params=q)
        out = self.wrap_result(ctx.client.raise_for_status(resp), _meta(ctx))
        ctx.cache.set(key, out, ttl_s=120.0)
        return out


class DescribeActionTool(BaseTool):
    name: ClassVar[str] = "describe_action"
    read_only: ClassVar[bool | None] = True
    description: ClassVar[str] = (
        "Show the inputs one action accepts: path_params, query filters, and body fields with types "
        "and allowed values. The workspace is filled in for you."
    )

    @classmethod
    def input_schema(cls) -> dict[str, Any]:
        return DescribeActionParams.model_json_schema()

    async def run(self, ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
        p = validate_args(params, DescribeActionParams)
        method, path = split_action(p.action)
        return self.wrap_result(await describe_cached(ctx, f"{method} {path}"), _meta(ctx))


class CallReadActionTool(BaseTool):
    name: ClassVar[str] = "call_read_action"
    read_only: ClassVar[bool | None] = True
    description: ClassVar[str] = (
        "Run a GET action from search_actions. Pass path_params for {placeholders} and query for "
        "filters, sorting, and paging. Large results are trimmed and say how many rows came back."
    )

    @classmethod
    def input_schema(cls) -> dict[str, Any]:
        return CallReadActionParams.model_json_schema()

    async def run(self, ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
        p = validate_args(params, CallReadActionParams)
        method, template = split_action(p.action)
        if method != "GET":
            raise ValueError("call_read_action runs GET actions. Use call_write_action for changes.")
        template, _ = await resolve_action(ctx, method, template)
        ws = ctx.auth.workspace_id
        path = fill_path(template, p.path_params, ws)
        query = _clean_query(p.query, ws)
        key = ctx.cache.key_for(ws, self.name, {"path": path, "query": query, "max": p.max_chars})
        hit = ctx.cache.get(key)
        if hit is not None:
            return hit
        resp = await ctx.client._request_with_retries("GET", path, auth=ctx.auth, params=query)
        body = ctx.client.raise_for_status(resp)
        out = self.wrap_result(fit(body, p.max_chars), _meta(ctx))
        ctx.cache.set(key, out)
        return out


class CallWriteActionTool(BaseTool):
    name: ClassVar[str] = "call_write_action"
    read_only: ClassVar[bool | None] = False
    destructive: ClassVar[bool | None] = True
    description: ClassVar[str] = (
        "Run a create, edit, delete, or send action from search_actions. Call describe_action first "
        "to see the body fields. Repeating the same call with the same idempotency_key is safe."
    )

    @classmethod
    def input_schema(cls) -> dict[str, Any]:
        return CallWriteActionParams.model_json_schema()

    async def run(self, ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
        p = validate_args(params, CallWriteActionParams)
        method, template = split_action(p.action)
        if method not in _WRITE_METHODS:
            raise ValueError("call_write_action runs POST, PUT, PATCH, or DELETE actions.")
        template, described = await resolve_action(ctx, method, template)
        ws = ctx.auth.workspace_id
        path = fill_path(template, p.path_params, ws)
        query = _clean_query(p.query, ws)
        body = p.body
        if isinstance(body, dict):
            body = {k: v for k, v in body.items() if str(k).lower() != "workspace_id"}
            if "body.workspace_id" in (described.get("injected") or []):
                body["workspace_id"] = ws
        if ctx.settings.dry_run:
            return self.wrap_result({"dry_run": True, "method": method, "path": path, "query": query, "body": body}, _meta(ctx))

        idem = p.idempotency_key or compute_idempotency_key(
            ws,
            self.name,
            self.version,
            {"user": ctx.auth.user_id, "method": method, "path": path, "query": query, "body": body},
        )
        try:
            resp = await ctx.client._request_with_retries(
                method,
                path,
                auth=ctx.auth,
                params=query,
                json_body=body if method != "DELETE" or body else None,
                idempotency_key=idem,
            )
            out_body = ctx.client.raise_for_status(resp)
            log_write_tool_invoked(
                tool=f"{self.name}:{method} {template}",
                idempotency_key=idem,
                request_id=ctx.request_id,
                status="success",
                outcome_body=out_body if isinstance(out_body, dict) else None,
            )
        except Exception:
            log_write_tool_invoked(
                tool=f"{self.name}:{method} {template}",
                idempotency_key=idem,
                request_id=ctx.request_id,
                status="error",
            )
            raise
        ctx.cache.invalidate_prefix(f"{ws}:")
        return self.wrap_result(fit(out_body, p.max_chars), _meta(ctx))
