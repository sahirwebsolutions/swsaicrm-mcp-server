"""Contact tools — backed by FastAPI /api/v1/contacts."""

from __future__ import annotations

import json
from typing import Any, ClassVar
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from idempotency_keys import compute_idempotency_key, compute_stable_update_idempotency_key
from unified_transport import execute_via_unified, routes_via_unified_executor
from middleware import ToolContext
from tool_logging import log_write_tool_invoked
from tools.base import BaseTool, ToolExecuteContext, validate_args
from write_helpers import finalize_write_success, guard_try_cached


def _split_name(full: str) -> tuple[str, str]:
    parts = full.strip().split(None, 1)
    if not parts:
        return ("", "")
    if len(parts) == 1:
        return (parts[0], "")
    return (parts[0], parts[1])


class SearchContactsParams(BaseModel):
    model_config = {"extra": "forbid"}

    query: str | None = Field(None, max_length=512)
    search: str | None = Field(None, max_length=512)
    limit: int = Field(20, ge=1, le=200)
    page: int | None = Field(None, ge=1)
    cursor: str | None = None
    status: str | None = Field(None, max_length=50)
    source: str | None = Field(None, max_length=100)
    filter_id: UUID | None = None
    criteria: dict[str, Any] | None = None
    filters: dict[str, Any] | None = None
    unclaimed_leads: bool | None = None
    unclaimed_pond_id: UUID | None = None
    sort_by: str | None = Field(None, max_length=80)
    sort_order: str | None = Field(None, pattern="^(asc|desc)$")


class GetContactParams(BaseModel):
    model_config = {"extra": "forbid"}

    contact_id: UUID


class CreateContactParams(BaseModel):
    model_config = {"extra": "forbid"}

    name: str = Field(..., min_length=1, max_length=200)
    email: EmailStr | None = None
    phone: str | None = Field(None, max_length=50)
    status: str | None = Field(None, max_length=50)


class UpdateContactParams(BaseModel):
    model_config = {"extra": "forbid"}

    contact_id: UUID
    first_name: str | None = Field(None, min_length=1, max_length=100)
    last_name: str | None = Field(None, max_length=100)
    email: EmailStr | None = None
    phone: str | None = Field(None, max_length=50)
    status: str | None = Field(None, max_length=50)
    company: str | None = Field(None, max_length=255)


class DeleteContactParams(BaseModel):
    model_config = {"extra": "forbid"}

    contact_id: UUID


class AddContactNoteParams(BaseModel):
    model_config = {"extra": "forbid"}

    contact_id: UUID
    content: str = Field(..., min_length=1, max_length=10000)
    title: str | None = Field(None, max_length=255)


class SearchContactsTool(BaseTool):
    name: ClassVar[str] = "search_contacts"
    description: ClassVar[str] = (
        "Use when the user wants to find, list, count, or filter contacts or leads "
        "(e.g. 'find John', 'how many leads from Facebook'). Read-only."
    )

    @classmethod
    def input_schema(cls) -> dict[str, Any]:
        return SearchContactsParams.model_json_schema()

    async def run(self, ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
        p = validate_args(params, SearchContactsParams)
        max_lim = min(p.limit, ctx.settings.tool_max_results)

        if routes_via_unified_executor(self.name):
            unified_payload: dict[str, Any] = {
                "search": p.search or p.query,
                "limit": max_lim,
            }
            if p.page:
                unified_payload["page"] = p.page
            if p.cursor:
                unified_payload["cursor"] = p.cursor
            if p.status:
                unified_payload["status"] = p.status
            if p.source:
                unified_payload["source"] = p.source
            if p.filter_id:
                unified_payload["filter_id"] = str(p.filter_id)
            if p.criteria:
                unified_payload["criteria"] = p.criteria
            if p.filters:
                unified_payload["filters"] = p.filters
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

        ws = ctx.auth.workspace_id
        key = ctx.cache.key_for(ws, self.name, {"search": p.search, "limit": max_lim, "cursor": p.cursor})
        hit = ctx.cache.get(key)
        if hit is not None:
            return hit

        q: dict[str, Any] = {
            "workspace_id": ws,
            "search": p.search or p.query,
            "limit": max_lim,
        }
        if p.page:
            q["page"] = p.page
        if p.cursor:
            q["cursor"] = p.cursor
        if p.status:
            q["status"] = p.status
        if p.source:
            q["source"] = p.source
        if p.filter_id:
            q["filter_id"] = str(p.filter_id)
        if p.criteria:
            q["criteria"] = json.dumps(p.criteria, separators=(",", ":"))
        if p.filters:
            q["filters"] = json.dumps(p.filters, separators=(",", ":"))
        if p.unclaimed_leads is not None:
            q["unclaimed_leads"] = str(bool(p.unclaimed_leads)).lower()
        if p.unclaimed_pond_id:
            q["unclaimed_pond_id"] = str(p.unclaimed_pond_id)
        if p.sort_by:
            q["sort_by"] = p.sort_by
        if p.sort_order:
            q["sort_order"] = p.sort_order

        resp = await ctx.client._request_with_retries(
            "GET",
            "/api/v1/contacts",
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


class ContactsSearchTool(SearchContactsTool):
    name: ClassVar[str] = "contacts_search"
    description: ClassVar[str] = (
        "Use when the user wants to find, list, count, or filter contacts/leads with "
        "combined filters (status, source, saved filter). Read-only. Same as search_contacts."
    )


class GetContactTool(BaseTool):
    name: ClassVar[str] = "get_contact"
    description: ClassVar[str] = (
        "Use when the user asks for the full details of ONE specific contact you already "
        "have the id for. Read-only. To search by name, use search_contacts first."
    )

    @classmethod
    def input_schema(cls) -> dict[str, Any]:
        return GetContactParams.model_json_schema()

    async def run(self, ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
        p = validate_args(params, GetContactParams)
        ws = ctx.auth.workspace_id
        key = ctx.cache.key_for(ws, self.name, {"contact_id": str(p.contact_id)})
        hit = ctx.cache.get(key)
        if hit is not None:
            return hit

        path = f"/api/v1/contacts/{p.contact_id}"
        q = {"workspace_id": ws}
        resp = await ctx.client._request_with_retries("GET", path, auth=ctx.auth, params=q)
        body = ctx.client.raise_for_status(resp)
        te = ToolExecuteContext(
            user_id=ctx.auth.user_id,
            workspace_id=ctx.auth.workspace_id,
            request_id=ctx.request_id,
        )
        out = self.wrap_result(body, te)
        ctx.cache.set(key, out)
        return out


class CreateContactTool(BaseTool):
    name: ClassVar[str] = "create_contact"
    description: ClassVar[str] = (
        "Use when the user wants to add a new contact or lead (e.g. 'add a contact named…')."
    )

    @classmethod
    def input_schema(cls) -> dict[str, Any]:
        return CreateContactParams.model_json_schema()

    async def run(self, ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
        p = validate_args(params, CreateContactParams)
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

        idem_payload = {k: v for k, v in snap.items() if v is not None}
        idem = compute_idempotency_key(ws, self.name, self.version, idem_payload)

        fn, ln = _split_name(p.name)
        body: dict[str, Any] = {"first_name": fn, "last_name": ln or None}
        if p.email:
            body["email"] = str(p.email)
        if p.phone:
            body["phone"] = p.phone
        if p.status:
            body["status"] = p.status

        try:
            resp = await ctx.client._request_with_retries(
                "POST",
                "/api/v1/contacts/",
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


class UpdateContactTool(BaseTool):
    name: ClassVar[str] = "update_contact"
    description: ClassVar[str] = (
        "Use when the user wants to change a contact's fields — name, email, phone, "
        "status, or company (e.g. 'update John's phone number')."
    )

    @classmethod
    def input_schema(cls) -> dict[str, Any]:
        return UpdateContactParams.model_json_schema()

    async def run(self, ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
        p = validate_args(params, UpdateContactParams)
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
            ws, self.name, self.version, str(p.contact_id), "update_fields"
        )

        patch: dict[str, Any] = {}
        if p.first_name is not None:
            patch["first_name"] = p.first_name
        if p.last_name is not None:
            patch["last_name"] = p.last_name
        if p.email is not None:
            patch["email"] = str(p.email)
        if p.phone is not None:
            patch["phone"] = p.phone
        if p.status is not None:
            patch["status"] = p.status
        if p.company is not None:
            patch["company"] = p.company
        if not patch:
            raise ValueError("At least one field must be provided to update")

        path = f"/api/v1/contacts/{p.contact_id}"
        try:
            resp = await ctx.client._request_with_retries(
                "PUT",
                path,
                auth=ctx.auth,
                params={"workspace_id": ws},
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


class DeleteContactTool(BaseTool):
    name: ClassVar[str] = "delete_contact"
    description: ClassVar[str] = (
        "Use ONLY when the user explicitly asks to delete or remove a contact. "
        "Destructive and irreversible — confirm intent first."
    )

    @classmethod
    def input_schema(cls) -> dict[str, Any]:
        return DeleteContactParams.model_json_schema()

    async def run(self, ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
        p = validate_args(params, DeleteContactParams)
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
            ws, self.name, self.version, str(p.contact_id), "delete"
        )

        path = f"/api/v1/contacts/{p.contact_id}"
        try:
            resp = await ctx.client._request_with_retries(
                "DELETE",
                path,
                auth=ctx.auth,
                params={"workspace_id": ws},
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


class AddContactNoteTool(BaseTool):
    name: ClassVar[str] = "add_contact_note"
    description: ClassVar[str] = (
        "Use when the user wants to log a note or comment on a contact's record "
        "(e.g. 'add a note to John that he prefers email')."
    )

    @classmethod
    def input_schema(cls) -> dict[str, Any]:
        return AddContactNoteParams.model_json_schema()

    async def run(self, ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
        p = validate_args(params, AddContactNoteParams)
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

        idem_payload = {k: v for k, v in snap.items() if k != "contact_id" and v is not None}
        idem = compute_idempotency_key(ws, self.name, self.version, idem_payload)

        body: dict[str, Any] = {"content": p.content}
        if p.title:
            body["title"] = p.title

        path = f"/api/v1/contacts/{p.contact_id}/notes"
        try:
            resp = await ctx.client._request_with_retries(
                "POST",
                path,
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
