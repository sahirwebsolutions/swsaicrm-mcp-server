"""Task tools — FastAPI /api/v1/tasks."""

from __future__ import annotations

from typing import Any, ClassVar
from uuid import UUID

from pydantic import BaseModel, Field

from client import UpstreamError
from idempotency_keys import compute_idempotency_key, compute_stable_update_idempotency_key
from middleware import ToolContext
from tool_logging import log_write_tool_invoked
from tools.base import BaseTool, ToolExecuteContext, validate_args
from unified_transport import execute_via_unified, routes_via_unified_executor
from write_helpers import finalize_write_success, guard_try_cached


class ListTasksParams(BaseModel):
    model_config = {"extra": "forbid"}

    limit: int = Field(20, ge=1, le=100)
    cursor: str | None = None
    board_id: UUID | None = None
    search: str | None = Field(None, max_length=512)


class CreateTaskParams(BaseModel):
    model_config = {"extra": "forbid"}

    title: str = Field(..., min_length=1, max_length=1000)
    contact_id: UUID | None = None
    description: str | None = Field(None, max_length=4000)
    board_id: UUID | None = None
    group_id: UUID | None = None
    priority: str | None = Field(None, max_length=32)
    status: str | None = Field(None, max_length=64)
    idempotency_key: str | None = Field(None, max_length=128)


class UpdateTaskStatusParams(BaseModel):
    model_config = {"extra": "forbid"}

    task_id: UUID
    status: str = Field(..., min_length=1, max_length=64)
    idempotency_key: str | None = Field(None, max_length=128)


class ListTasksTool(BaseTool):
    name: ClassVar[str] = "list_tasks"
    description: ClassVar[str] = (
        "Use when the user wants to see, count, filter, or find tasks, to-dos, or "
        "follow-ups (e.g. 'my open tasks', 'how many tasks are pending'). Read-only."
    )

    @classmethod
    def input_schema(cls) -> dict[str, Any]:
        return ListTasksParams.model_json_schema()

    async def run(self, ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
        p = validate_args(params, ListTasksParams)
        max_lim = min(p.limit, ctx.settings.tool_max_results)
        ws = ctx.auth.workspace_id
        key = ctx.cache.key_for(
            ws,
            self.name,
            {
                "limit": max_lim,
                "cursor": p.cursor,
                "board_id": str(p.board_id) if p.board_id else None,
                "search": p.search,
            },
        )
        hit = ctx.cache.get(key)
        if hit is not None:
            return hit

        q: dict[str, Any] = {"workspace_id": ws, "limit": max_lim}
        if p.cursor:
            q["cursor"] = p.cursor
        if p.board_id:
            q["board_id"] = str(p.board_id)
        if p.search:
            q["search"] = p.search

        resp = await ctx.client._request_with_retries("GET", "/api/v1/tasks/", auth=ctx.auth, params=q)
        body = ctx.client.raise_for_status(resp)
        te = ToolExecuteContext(
            user_id=ctx.auth.user_id,
            workspace_id=ctx.auth.workspace_id,
            request_id=ctx.request_id,
        )
        out = self.wrap_result(body, te)
        ctx.cache.set(key, out)
        return out


class CreateTaskTool(BaseTool):
    name: ClassVar[str] = "create_task"
    description: ClassVar[str] = (
        "Use when the user wants to add a new task, to-do, follow-up, or reminder "
        "(e.g. 'create a task to…', 'remind me to…'). Creates it in the workspace."
    )

    @classmethod
    def input_schema(cls) -> dict[str, Any]:
        return CreateTaskParams.model_json_schema()

    async def run(self, ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
        p = validate_args(params, CreateTaskParams)
        if ctx.settings.dry_run:
            te = ToolExecuteContext(
                user_id=ctx.auth.user_id,
                workspace_id=ctx.auth.workspace_id,
                request_id=ctx.request_id,
            )
            return self.wrap_result({"dry_run": True, "would_create": True}, te)

        ws = ctx.auth.workspace_id

        # Governed path parity: route the write through the unified executor so
        # RBAC + policy + audit match the in-process Copilot path exactly.
        if routes_via_unified_executor(self.name):
            unified_payload: dict[str, Any] = {
                "title": p.title,
                "priority": p.priority or "medium",
                "status": p.status or "pending",
            }
            if p.description:
                unified_payload["description"] = p.description
            if p.contact_id:
                unified_payload["contact_id"] = str(p.contact_id)
            if p.board_id:
                unified_payload["board_id"] = str(p.board_id)
            if p.group_id:
                unified_payload["group_id"] = str(p.group_id)
            out = await execute_via_unified(
                ctx.client,
                ctx.auth,
                tool_name=self.name,
                payload=unified_payload,
            )
            te = ToolExecuteContext(
                user_id=ctx.auth.user_id,
                workspace_id=ctx.auth.workspace_id,
                request_id=ctx.request_id,
            )
            return self.wrap_result(out.get("data") or out, te)

        snap: dict[str, Any] = p.model_dump(mode="json")
        dup = guard_try_cached(ctx, self.name, ws, snap)
        if dup is not None:
            return dup

        idem_payload = {k: v for k, v in snap.items() if v is not None}
        idem = compute_idempotency_key(ws, self.name, self.version, idem_payload)

        body = {
            "workspace_id": ws,
            "title": p.title,
            "description": p.description,
            "contact_id": str(p.contact_id) if p.contact_id else None,
            "board_id": str(p.board_id) if p.board_id else None,
            "group_id": str(p.group_id) if p.group_id else None,
            "priority": p.priority or "medium",
            "status": p.status or "pending",
        }
        body = {k: v for k, v in body.items() if v is not None}
        try:
            resp = await ctx.client._request_with_retries(
                "POST",
                "/api/v1/tasks/",
                auth=ctx.auth,
                json_body=body,
                idempotency_key=idem,
            )
            out_body = ctx.client.raise_for_status(resp)
            log_write_tool_invoked(
                tool=self.name,
                idempotency_key=idem,
                request_id=ctx.request_id,
                status="success",
                outcome_body=out_body if isinstance(out_body, dict) else None,
            )
        except Exception:
            log_write_tool_invoked(
                tool=self.name,
                idempotency_key=idem,
                request_id=ctx.request_id,
                status="error",
            )
            raise

        te = ToolExecuteContext(
            user_id=ctx.auth.user_id,
            workspace_id=ctx.auth.workspace_id,
            request_id=ctx.request_id,
        )
        wrapped = self.wrap_result(out_body, te)
        finalize_write_success(
            ctx,
            self.name,
            ws,
            snap,
            wrapped,
            idem,
            out_body if isinstance(out_body, dict) else {},
        )
        return wrapped


class UpdateTaskStatusTool(BaseTool):
    name: ClassVar[str] = "update_task_status"
    description: ClassVar[str] = (
        "Use when the user wants to mark a task done/complete/in-progress or otherwise "
        "change a task's status (e.g. 'mark task X as done', 'move it to in progress')."
    )

    @classmethod
    def input_schema(cls) -> dict[str, Any]:
        return UpdateTaskStatusParams.model_json_schema()

    async def run(self, ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
        p = validate_args(params, UpdateTaskStatusParams)
        if ctx.settings.dry_run:
            te = ToolExecuteContext(
                user_id=ctx.auth.user_id,
                workspace_id=ctx.auth.workspace_id,
                request_id=ctx.request_id,
            )
            return self.wrap_result({"dry_run": True, "would_update_task_id": str(p.task_id)}, te)

        ws = ctx.auth.workspace_id

        if routes_via_unified_executor(self.name):
            out = await execute_via_unified(
                ctx.client,
                ctx.auth,
                tool_name=self.name,
                payload={"task_id": str(p.task_id), "status": p.status},
            )
            te = ToolExecuteContext(
                user_id=ctx.auth.user_id,
                workspace_id=ctx.auth.workspace_id,
                request_id=ctx.request_id,
            )
            return self.wrap_result(out.get("data") or out, te)

        snap: dict[str, Any] = p.model_dump(mode="json")
        dup = guard_try_cached(ctx, self.name, ws, snap)
        if dup is not None:
            return dup

        idem = compute_stable_update_idempotency_key(
            ws, self.name, self.version, str(p.task_id), "update_status"
        )

        payload = {"status": p.status}
        path = f"/api/v1/tasks/{p.task_id}"
        try:
            resp = await ctx.client._request_with_retries(
                "PUT",
                path,
                auth=ctx.auth,
                json_body=payload,
                idempotency_key=idem,
            )
            out_body = ctx.client.raise_for_status(resp)
            log_write_tool_invoked(
                tool=self.name,
                idempotency_key=idem,
                request_id=ctx.request_id,
                status="success",
                outcome_body=out_body if isinstance(out_body, dict) else None,
            )
        except Exception:
            log_write_tool_invoked(
                tool=self.name,
                idempotency_key=idem,
                request_id=ctx.request_id,
                status="error",
            )
            raise

        te = ToolExecuteContext(
            user_id=ctx.auth.user_id,
            workspace_id=ctx.auth.workspace_id,
            request_id=ctx.request_id,
        )
        wrapped = self.wrap_result(out_body, te)
        finalize_write_success(
            ctx,
            self.name,
            ws,
            snap,
            wrapped,
            idem,
            out_body if isinstance(out_body, dict) else {},
        )
        return wrapped
