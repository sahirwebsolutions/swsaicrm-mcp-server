"""Note tools — FastAPI /api/v1/contacts notes endpoints."""

from __future__ import annotations

from typing import Any, ClassVar
from uuid import UUID

from pydantic import BaseModel, Field

from middleware import ToolContext
from tools.base import BaseTool, ToolExecuteContext, validate_args


class ListContactNotesParams(BaseModel):
    model_config = {"extra": "forbid"}

    contact_id: UUID


class SearchNotesParams(BaseModel):
    model_config = {"extra": "forbid"}

    query: str = Field(..., min_length=2, max_length=512)
    limit: int = Field(20, ge=1, le=100)


class ListContactNotesTool(BaseTool):
    name: ClassVar[str] = "list_contact_notes"
    description: ClassVar[str] = (
        "Use when the user wants to read the notes logged on a specific contact "
        "(you must have the contact_id). Read-only."
    )

    @classmethod
    def input_schema(cls) -> dict[str, Any]:
        return ListContactNotesParams.model_json_schema()

    async def run(self, ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
        p = validate_args(params, ListContactNotesParams)
        ws = ctx.auth.workspace_id
        key = ctx.cache.key_for(ws, self.name, {"contact_id": str(p.contact_id)})
        hit = ctx.cache.get(key)
        if hit is not None:
            return hit

        resp = await ctx.client._request_with_retries(
            "GET",
            f"/api/v1/contacts/{p.contact_id}/notes",
            auth=ctx.auth,
            params={"workspace_id": ws},
        )
        body = ctx.client.raise_for_status(resp)
        te = ToolExecuteContext(
            user_id=ctx.auth.user_id,
            workspace_id=ctx.auth.workspace_id,
            request_id=ctx.request_id,
        )
        out = self.wrap_result({"notes": body}, te)
        ctx.cache.set(key, out)
        return out


class SearchNotesTool(BaseTool):
    name: ClassVar[str] = "search_notes"
    description: ClassVar[str] = (
        "Use when the user wants to find notes across all contacts by keyword "
        "(e.g. 'find notes mentioning refund'). Read-only."
    )

    @classmethod
    def input_schema(cls) -> dict[str, Any]:
        return SearchNotesParams.model_json_schema()

    async def run(self, ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
        p = validate_args(params, SearchNotesParams)
        ws = ctx.auth.workspace_id
        max_lim = min(p.limit, ctx.settings.tool_max_results)
        key = ctx.cache.key_for(ws, self.name, {"query": p.query, "limit": max_lim})
        hit = ctx.cache.get(key)
        if hit is not None:
            return hit

        resp = await ctx.client._request_with_retries(
            "GET",
            "/api/v1/contacts/notes/search",
            auth=ctx.auth,
            params={"workspace_id": ws, "query": p.query, "limit": max_lim},
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
