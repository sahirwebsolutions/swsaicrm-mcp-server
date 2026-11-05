"""Task boards — FastAPI /api/v1/task-boards."""

from __future__ import annotations

from typing import Any, ClassVar
from uuid import UUID

from pydantic import BaseModel, Field

from idempotency_keys import compute_idempotency_key, compute_stable_update_idempotency_key
from middleware import ToolContext
from tool_logging import log_write_tool_invoked
from tools.base import BaseTool, ToolExecuteContext, validate_args
from write_helpers import finalize_write_success, guard_try_cached


class ListBoardsParams(BaseModel):
    model_config = {"extra": "forbid"}


class CreateBoardParams(BaseModel):
    model_config = {"extra": "forbid"}

    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(None, max_length=2000)
    is_private: bool = True


class UpdateBoardParams(BaseModel):
    model_config = {"extra": "forbid"}

    board_id: UUID
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = Field(None, max_length=2000)
    is_default: bool | None = None
    is_private: bool | None = None


class DeleteBoardParams(BaseModel):
    model_config = {"extra": "forbid"}

    board_id: UUID


class ListBoardsTool(BaseTool):
    name: ClassVar[str] = "list_boards"
    description: ClassVar[str] = (
        "Use when the user wants to see the task boards (kanban) in the workspace, or to "
        "find a board id before creating/moving a task. Read-only."
    )

    @classmethod
    def input_schema(cls) -> dict[str, Any]:
        return ListBoardsParams.model_json_schema()

    async def run(self, ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
        validate_args(params, ListBoardsParams)
        ws = ctx.auth.workspace_id
        key = ctx.cache.key_for(ws, self.name, {})
        hit = ctx.cache.get(key)
        if hit is not None:
            return hit

        q = {"workspace_id": ws}
        resp = await ctx.client._request_with_retries(
            "GET",
            "/api/v1/task-boards",
            auth=ctx.auth,
            params=q,
        )
        body = ctx.client.raise_for_status(resp)
        te = ToolExecuteContext(
            user_id=ctx.auth.user_id,
            workspace_id=ctx.auth.workspace_id,
            request_id=ctx.request_id,
        )
        out = self.wrap_result(body, te)
        ctx.cache.set(key, out)
        return out


class CreateBoardTool(BaseTool):
    name: ClassVar[str] = "create_board"
    description: ClassVar[str] = (
        "Use when the user wants to add a new task board (kanban) to organize tasks."
    )

    @classmethod
    def input_schema(cls) -> dict[str, Any]:
        return CreateBoardParams.model_json_schema()

    async def run(self, ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
        p = validate_args(params, CreateBoardParams)
        if ctx.settings.dry_run:
            te = ToolExecuteContext(
                user_id=ctx.auth.user_id,
                workspace_id=ctx.auth.workspace_id,
                request_id=ctx.request_id,
            )
            return self.wrap_result({"dry_run": True}, te)

        ws = ctx.auth.workspace_id
        snap = p.model_dump(mode="json")
        dup = guard_try_cached(ctx, self.name, ws, snap)
        if dup is not None:
            return dup

        idem = compute_idempotency_key(ws, self.name, self.version, snap)

        body = {
            "name": p.name,
            "description": p.description,
            "is_private": p.is_private,
            "is_default": False,
        }
        body = {k: v for k, v in body.items() if v is not None}
        try:
            resp = await ctx.client._request_with_retries(
                "POST",
                "/api/v1/task-boards",
                auth=ctx.auth,
                params={"workspace_id": ws},
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


class UpdateBoardTool(BaseTool):
    name: ClassVar[str] = "update_board"
    description: ClassVar[str] = (
        "Use when the user wants to rename or reconfigure an existing task board."
    )

    @classmethod
    def input_schema(cls) -> dict[str, Any]:
        return UpdateBoardParams.model_json_schema()

    async def run(self, ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
        p = validate_args(params, UpdateBoardParams)
        if ctx.settings.dry_run:
            te = ToolExecuteContext(
                user_id=ctx.auth.user_id,
                workspace_id=ctx.auth.workspace_id,
                request_id=ctx.request_id,
            )
            return self.wrap_result({"dry_run": True}, te)

        ws = ctx.auth.workspace_id
        snap = p.model_dump(mode="json")
        dup = guard_try_cached(ctx, self.name, ws, snap)
        if dup is not None:
            return dup

        idem = compute_stable_update_idempotency_key(
            ws, self.name, self.version, str(p.board_id), "update_fields"
        )

        patch: dict[str, Any] = {}
        if p.name is not None:
            patch["name"] = p.name
        if p.description is not None:
            patch["description"] = p.description
        if p.is_default is not None:
            patch["is_default"] = p.is_default
        if p.is_private is not None:
            patch["is_private"] = p.is_private
        if not patch:
            raise ValueError("At least one field must be provided")

        path = f"/api/v1/task-boards/{p.board_id}"
        try:
            resp = await ctx.client._request_with_retries(
                "PUT",
                path,
                auth=ctx.auth,
                json_body=patch,
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


class DeleteBoardTool(BaseTool):
    name: ClassVar[str] = "delete_board"
    description: ClassVar[str] = (
        "Use ONLY when the user explicitly asks to delete a task board. Destructive — "
        "this removes the board and confirm intent first."
    )

    @classmethod
    def input_schema(cls) -> dict[str, Any]:
        return DeleteBoardParams.model_json_schema()

    async def run(self, ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
        p = validate_args(params, DeleteBoardParams)
        if ctx.settings.dry_run:
            te = ToolExecuteContext(
                user_id=ctx.auth.user_id,
                workspace_id=ctx.auth.workspace_id,
                request_id=ctx.request_id,
            )
            return self.wrap_result({"dry_run": True}, te)

        ws = ctx.auth.workspace_id
        snap = p.model_dump(mode="json")
        dup = guard_try_cached(ctx, self.name, ws, snap)
        if dup is not None:
            return dup

        idem = compute_stable_update_idempotency_key(
            ws, self.name, self.version, str(p.board_id), "delete"
        )

        path = f"/api/v1/task-boards/{p.board_id}"
        try:
            resp = await ctx.client._request_with_retries(
                "DELETE",
                path,
                auth=ctx.auth,
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
