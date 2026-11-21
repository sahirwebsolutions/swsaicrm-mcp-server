"""Task tools — FastAPI /api/v1/tasks."""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any, ClassVar, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from date_range import _today, parse_relative_range
from idempotency_keys import compute_idempotency_key, compute_stable_update_idempotency_key
from middleware import ToolContext
from response_shape import fit
from tool_logging import log_write_tool_invoked
from tools.base import BaseTool, ToolExecuteContext, validate_args
from unified_transport import execute_via_unified, routes_via_unified_executor
from write_helpers import finalize_write_success, guard_try_cached

Priority = Literal["low", "medium", "high", "urgent"]
SortBy = Literal["due_date", "updated_at", "created_at", "priority", "title", "assigned_to"]

_TASK_LIST_MAX_CHARS = 60_000
CLOSED_STATUSES = frozenset({"completed", "complete", "done", "cancelled", "canceled", "closed"})


class ListTasksParams(BaseModel):
    model_config = {"extra": "forbid"}

    limit: int = Field(25, ge=1, le=100)
    cursor: str | None = Field(None, description="next_cursor from the previous page")
    search: str | None = Field(None, max_length=512, description="Words in the title or description")
    status: list[str] | None = Field(
        None,
        description="Statuses to include, e.g. ['pending', 'in_progress']. Boards may define their own statuses.",
    )
    priority: list[Priority] | None = None
    assignee: list[str] | None = Field(
        None,
        description="Assignee profile ids, or 'me' for the signed-in member",
    )
    due: str | None = Field(
        None,
        max_length=40,
        description="Due window in words: overdue, today, tomorrow, this week, next week, next 7 days, this month, last 30 days",
    )
    due_from: str | None = Field(None, description="Due on or after this ISO date")
    due_to: str | None = Field(None, description="Due on or before this ISO date")
    created: str | None = Field(None, max_length=40, description="Created window in words, e.g. 'last 7 days'")
    created_from: str | None = None
    created_to: str | None = None
    board_id: UUID | None = None
    group_id: UUID | None = None
    all_boards: bool = Field(
        False,
        description="Every staff board in the workspace. Needs the 'view all tasks' permission.",
    )
    include_closed: bool | None = Field(
        None,
        description="Include completed and cancelled tasks. Defaults to false for 'overdue', true otherwise.",
    )
    sort_by: SortBy = "due_date"
    sort_order: Literal["asc", "desc"] = "asc"


class TaskIdParams(BaseModel):
    model_config = {"extra": "forbid"}

    task_id: UUID


class CreateTaskParams(BaseModel):
    model_config = {"extra": "forbid"}

    title: str = Field(..., min_length=1, max_length=1000)
    description: str | None = Field(None, max_length=1000)
    contact_id: UUID | None = None
    board_id: UUID | None = None
    group_id: UUID | None = None
    parent_task_id: UUID | None = Field(None, description="Set to create a subtask")
    priority: Priority | None = None
    status: str | None = Field(None, max_length=64)
    due_date: str | None = Field(None, description="ISO date or date-time")
    start_date: str | None = Field(None, description="ISO date or date-time")
    assigned_to: str | None = Field(None, description="Assignee profile id, or 'me'")
    tags: list[str] | None = None
    idempotency_key: str | None = Field(None, max_length=128)


class UpdateTaskParams(BaseModel):
    model_config = {"extra": "forbid"}

    task_id: UUID
    title: str | None = Field(None, min_length=1, max_length=1000)
    description: str | None = Field(None, max_length=1000)
    status: str | None = Field(None, max_length=64)
    priority: Priority | None = None
    due_date: str | None = Field(None, description="ISO date or date-time. Use clear_due_date to remove it.")
    clear_due_date: bool = False
    start_date: str | None = None
    assigned_to: str | None = Field(None, description="Assignee profile id, or 'me'")
    assignees: list[str] | None = Field(None, description="Replaces all assignees; the first is primary")
    followers: list[str] | None = None
    contact_id: UUID | None = None
    board_id: UUID | None = Field(None, description="Move to this board")
    group_id: UUID | None = Field(None, description="Move to this group")
    parent_task_id: UUID | None = None
    tags: list[str] | None = None
    idempotency_key: str | None = Field(None, max_length=128)


class UpdateTaskStatusParams(BaseModel):
    model_config = {"extra": "forbid"}

    task_id: UUID
    status: str = Field(..., min_length=1, max_length=64)
    idempotency_key: str | None = Field(None, max_length=128)


def _meta(ctx: ToolContext) -> ToolExecuteContext:
    return ToolExecuteContext(user_id=ctx.auth.user_id, workspace_id=ctx.auth.workspace_id, request_id=ctx.request_id)


def _who(value: str | None, ctx: ToolContext) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if text.lower() in ("me", "self", "myself"):
        return ctx.auth.user_id
    try:
        return str(UUID(text))
    except ValueError as exc:
        raise ValueError(f"Assignee must be a profile id or 'me' (got {text!r})") from exc


def _day_start(day: str | None) -> str | None:
    return f"{day}T00:00:00Z" if day and "T" not in day else day


def _day_end(day: str | None) -> str | None:
    return f"{day}T23:59:59.999Z" if day and "T" not in day else day


def due_window(expr: str | None, start: str | None, end: str | None) -> tuple[str | None, str | None]:
    """Resolve a due window, including forward-looking words the generic parser leaves out."""
    if start or end or not expr:
        s, e = parse_relative_range(None, start=start, end=end)
        return s, e
    text = expr.strip().lower()
    today = _today()
    if text in ("overdue", "past due", "late"):
        return None, (today - timedelta(days=1)).isoformat()
    if text == "tomorrow":
        day = (today + timedelta(days=1)).isoformat()
        return day, day
    if text in ("this week", "due this week"):
        monday = today - timedelta(days=today.weekday())
        return monday.isoformat(), (monday + timedelta(days=6)).isoformat()
    if text == "next week":
        monday = today - timedelta(days=today.weekday()) + timedelta(days=7)
        return monday.isoformat(), (monday + timedelta(days=6)).isoformat()
    if text == "this month":
        first = today.replace(day=1)
        nxt = (first + timedelta(days=32)).replace(day=1)
        return first.isoformat(), (nxt - timedelta(days=1)).isoformat()
    match = re.match(r"(?:next|coming)\s+(\d+)\s*(day|days|week|weeks)", text)
    if match:
        n = int(match.group(1)) * (7 if match.group(2).startswith("week") else 1)
        return today.isoformat(), (today + timedelta(days=n)).isoformat()
    s, e = parse_relative_range(text)
    if s is None and e is None:
        raise ValueError(f"Could not read the due window {expr!r}. Use words like 'overdue' or ISO dates.")
    return s, e


def _iso_date(value: str | None, label: str) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if "T" in text or "t" in text:
            from datetime import datetime

            datetime.fromisoformat(text.replace("Z", "+00:00"))
            return text
        return date.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO date like 2026-11-10") from exc


def _date_time(value: str | None, label: str) -> str | None:
    parsed = _iso_date(value, label)
    if parsed and "T" not in parsed:
        return f"{parsed}T00:00:00Z"
    return parsed


class ListTasksTool(BaseTool):
    name: ClassVar[str] = "list_tasks"
    description: ClassVar[str] = (
        "Find tasks with filters: status, priority, assignee ('me'), due window ('overdue', "
        "'today', 'this week', 'next 7 days'), created window, board, group, and text. Sort by due "
        "date, priority, or recency. Page with cursor. Read-only."
    )

    @classmethod
    def input_schema(cls) -> dict[str, Any]:
        return ListTasksParams.model_json_schema()

    async def run(self, ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
        p = validate_args(params, ListTasksParams)
        ws = ctx.auth.workspace_id
        due_from, due_to = due_window(p.due, _iso_date(p.due_from, "due_from"), _iso_date(p.due_to, "due_to"))
        created_from, created_to = parse_relative_range(
            p.created,
            start=_iso_date(p.created_from, "created_from"),
            end=_iso_date(p.created_to, "created_to"),
        )
        q: dict[str, Any] = {
            "workspace_id": ws,
            "limit": min(p.limit, 100),
            "sort_by": p.sort_by,
            "sort_order": p.sort_order,
        }
        optional = {
            "cursor": p.cursor,
            "search": p.search,
            "board_id": str(p.board_id) if p.board_id else None,
            "group_id": str(p.group_id) if p.group_id else None,
            "status": [s.strip().lower() for s in p.status if s.strip()] if p.status else None,
            "priority": list(p.priority) if p.priority else None,
            "assigned_to": [_who(a, ctx) for a in p.assignee] if p.assignee else None,
            "due_date_from": _day_start(due_from),
            "due_date_to": _day_end(due_to),
            "created_from": _day_start(created_from),
            "created_to": _day_end(created_to),
            "scope": "all" if p.all_boards else None,
        }
        q.update({k: v for k, v in optional.items() if v not in (None, [], "")})

        key = ctx.cache.key_for(ws, self.name, q)
        hit = ctx.cache.get(key)
        if hit is not None:
            return hit
        resp = await ctx.client._request_with_retries("GET", "/api/v1/tasks/", auth=ctx.auth, params=q)
        body = ctx.client.raise_for_status(resp)
        include_closed = p.include_closed
        if include_closed is None:
            include_closed = (p.due or "").strip().lower() not in ("overdue", "past due", "late")
        if isinstance(body, dict):
            applied = {k: v for k, v in q.items() if k != "workspace_id"}
            rows = body.get("tasks")
            if not include_closed and not p.status and isinstance(rows, list):
                kept = [t for t in rows if str((t or {}).get("status") or "").lower() not in CLOSED_STATUSES]
                body = {**body, "tasks": kept}
                applied["hidden_closed"] = len(rows) - len(kept)
            body = {**body, "filters_applied": applied}
        out = self.wrap_result(fit(body, _TASK_LIST_MAX_CHARS), _meta(ctx))
        ctx.cache.set(key, out)
        return out


class GetTaskTool(BaseTool):
    name: ClassVar[str] = "get_task"
    description: ClassVar[str] = "Read one task in full: description, dates, assignees, followers, tags, and custom fields."

    @classmethod
    def input_schema(cls) -> dict[str, Any]:
        return TaskIdParams.model_json_schema()

    async def run(self, ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
        p = validate_args(params, TaskIdParams)
        ws = ctx.auth.workspace_id
        key = ctx.cache.key_for(ws, self.name, {"task_id": str(p.task_id)})
        hit = ctx.cache.get(key)
        if hit is not None:
            return hit
        resp = await ctx.client._request_with_retries(
            "GET",
            f"/api/v1/tasks/{p.task_id}",
            auth=ctx.auth,
            params={"workspace_id": ws},
        )
        out = self.wrap_result(ctx.client.raise_for_status(resp), _meta(ctx))
        ctx.cache.set(key, out)
        return out


async def _write(
    tool: BaseTool,
    ctx: ToolContext,
    method: str,
    path: str,
    body: dict[str, Any] | None,
    idem: str,
    snap: dict[str, Any],
) -> dict[str, Any]:
    ws = ctx.auth.workspace_id
    dup = guard_try_cached(ctx, tool.name, ws, snap)
    if dup is not None:
        return dup
    try:
        resp = await ctx.client._request_with_retries(
            method,
            path,
            auth=ctx.auth,
            params={"workspace_id": ws},
            json_body=body,
            idempotency_key=idem,
        )
        out_body = ctx.client.raise_for_status(resp)
        log_write_tool_invoked(
            tool=tool.name,
            idempotency_key=idem,
            request_id=ctx.request_id,
            status="success",
            outcome_body=out_body if isinstance(out_body, dict) else None,
        )
    except Exception:
        log_write_tool_invoked(tool=tool.name, idempotency_key=idem, request_id=ctx.request_id, status="error")
        raise
    wrapped = tool.wrap_result(out_body, _meta(ctx))
    finalize_write_success(ctx, tool.name, ws, snap, wrapped, idem, out_body if isinstance(out_body, dict) else {})
    return wrapped


class CreateTaskTool(BaseTool):
    name: ClassVar[str] = "create_task"
    description: ClassVar[str] = (
        "Create a task, to-do, follow-up, or subtask with due date, assignee ('me' works), priority, "
        "board, group, contact, and tags."
    )

    @classmethod
    def input_schema(cls) -> dict[str, Any]:
        return CreateTaskParams.model_json_schema()

    async def run(self, ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
        p = validate_args(params, CreateTaskParams)
        if ctx.settings.dry_run:
            return self.wrap_result({"dry_run": True, "would_create": True}, _meta(ctx))
        ws = ctx.auth.workspace_id
        body: dict[str, Any] = {
            "workspace_id": ws,
            "title": p.title,
            "description": p.description,
            "contact_id": str(p.contact_id) if p.contact_id else None,
            "board_id": str(p.board_id) if p.board_id else None,
            "group_id": str(p.group_id) if p.group_id else None,
            "parent_task_id": str(p.parent_task_id) if p.parent_task_id else None,
            "priority": p.priority or "medium",
            "status": (p.status or "pending").strip().lower(),
            "due_date": _date_time(p.due_date, "due_date"),
            "start_date": _date_time(p.start_date, "start_date"),
            "assigned_to": _who(p.assigned_to, ctx),
            "tags": p.tags,
        }
        body = {k: v for k, v in body.items() if v is not None}

        if routes_via_unified_executor(self.name):
            payload = {k: v for k, v in body.items() if k != "workspace_id"}
            out = await execute_via_unified(ctx.client, ctx.auth, tool_name=self.name, payload=payload)
            return self.wrap_result(out.get("data") or out, _meta(ctx))

        snap = p.model_dump(mode="json")
        idem = p.idempotency_key or compute_idempotency_key(
            ws, self.name, self.version, {k: v for k, v in snap.items() if v is not None}
        )
        return await _write(self, ctx, "POST", "/api/v1/tasks/", body, idem, snap)


class UpdateTaskTool(BaseTool):
    name: ClassVar[str] = "update_task"
    description: ClassVar[str] = (
        "Change any part of a task: title, description, status, priority, due or start date, "
        "assignees, followers, contact, tags, or move it to another board or group. Send only the "
        "fields to change."
    )

    @classmethod
    def input_schema(cls) -> dict[str, Any]:
        return UpdateTaskParams.model_json_schema()

    async def run(self, ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
        p = validate_args(params, UpdateTaskParams)
        body: dict[str, Any] = {
            "title": p.title,
            "description": p.description,
            "status": p.status.strip().lower() if p.status else None,
            "priority": p.priority,
            "due_date": _date_time(p.due_date, "due_date"),
            "start_date": _date_time(p.start_date, "start_date"),
            "assigned_to": _who(p.assigned_to, ctx),
            "assignees": [_who(a, ctx) for a in p.assignees] if p.assignees is not None else None,
            "followers": [_who(a, ctx) for a in p.followers] if p.followers is not None else None,
            "contact_id": str(p.contact_id) if p.contact_id else None,
            "board_id": str(p.board_id) if p.board_id else None,
            "group_id": str(p.group_id) if p.group_id else None,
            "parent_task_id": str(p.parent_task_id) if p.parent_task_id else None,
            "tags": p.tags,
        }
        body = {k: v for k, v in body.items() if v is not None}
        if p.clear_due_date:
            body["due_date"] = None
        if not body:
            raise ValueError("Send at least one field to change")
        if ctx.settings.dry_run:
            return self.wrap_result({"dry_run": True, "would_update_task_id": str(p.task_id), "changes": body}, _meta(ctx))
        snap = p.model_dump(mode="json")
        idem = p.idempotency_key or compute_idempotency_key(
            ctx.auth.workspace_id,
            self.name,
            self.version,
            {k: v for k, v in snap.items() if v not in (None, False)},
        )
        return await _write(self, ctx, "PUT", f"/api/v1/tasks/{p.task_id}", body, idem, snap)


class DeleteTaskTool(BaseTool):
    name: ClassVar[str] = "delete_task"
    description: ClassVar[str] = "Delete one task. Confirm with the person first; this cannot be undone here."

    @classmethod
    def input_schema(cls) -> dict[str, Any]:
        return TaskIdParams.model_json_schema()

    async def run(self, ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
        p = validate_args(params, TaskIdParams)
        if ctx.settings.dry_run:
            return self.wrap_result({"dry_run": True, "would_delete_task_id": str(p.task_id)}, _meta(ctx))
        idem = compute_stable_update_idempotency_key(
            ctx.auth.workspace_id, self.name, self.version, str(p.task_id), "delete"
        )
        snap = p.model_dump(mode="json")
        return await _write(self, ctx, "DELETE", f"/api/v1/tasks/{p.task_id}", None, idem, snap)


class UpdateTaskStatusTool(BaseTool):
    name: ClassVar[str] = "update_task_status"
    description: ClassVar[str] = (
        "Mark a task done, in progress, or any other status (e.g. 'mark task X as done')."
    )

    @classmethod
    def input_schema(cls) -> dict[str, Any]:
        return UpdateTaskStatusParams.model_json_schema()

    async def run(self, ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
        p = validate_args(params, UpdateTaskStatusParams)
        if ctx.settings.dry_run:
            return self.wrap_result({"dry_run": True, "would_update_task_id": str(p.task_id)}, _meta(ctx))
        status = p.status.strip().lower()
        if routes_via_unified_executor(self.name):
            out = await execute_via_unified(
                ctx.client,
                ctx.auth,
                tool_name=self.name,
                payload={"task_id": str(p.task_id), "status": status},
            )
            return self.wrap_result(out.get("data") or out, _meta(ctx))
        idem = p.idempotency_key or compute_idempotency_key(
            ctx.auth.workspace_id, self.name, self.version, {"task_id": str(p.task_id), "status": status}
        )
        snap = p.model_dump(mode="json")
        return await _write(self, ctx, "PUT", f"/api/v1/tasks/{p.task_id}", {"status": status}, idem, snap)
