"""Document reads — FastAPI /api/v1/documents. Identity from auth only."""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, Field

from middleware import ToolContext
from tools.base import BaseTool, ToolExecuteContext, validate_args


class ListDocumentsParams(BaseModel):
    model_config = {"extra": "forbid"}

    query: str | None = Field(None, max_length=512)
    status: str | None = Field(None, max_length=64)
    limit: int = Field(20, ge=1, le=100)
    page: int = Field(1, ge=1)


class SearchDocumentsParams(BaseModel):
    model_config = {"extra": "forbid"}

    query: str = Field(..., min_length=1, max_length=512)
    limit: int = Field(20, ge=1, le=100)


class ListDocumentsTool(BaseTool):
    name: ClassVar[str] = "list_documents"
    description: ClassVar[str] = (
        "List CRM documents in the current workspace. Read-only. "
        "Workspace is taken from auth context."
    )

    @classmethod
    def input_schema(cls) -> dict[str, Any]:
        return ListDocumentsParams.model_json_schema()

    async def run(self, ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
        p = validate_args(params, ListDocumentsParams)
        ws = ctx.auth.workspace_id
        q: dict[str, Any] = {
            "workspace_id": ws,
            "page": p.page,
            "limit": min(p.limit, ctx.settings.tool_max_results),
        }
        if p.query:
            q["q"] = p.query
        if p.status:
            q["status"] = p.status
        key = ctx.cache.key_for(ws, self.name, q)
        hit = ctx.cache.get(key)
        if hit is not None:
            return hit
        resp = await ctx.client._request_with_retries(
            "GET", "/api/v1/documents", auth=ctx.auth, params=q
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


class SearchDocumentsTool(BaseTool):
    name: ClassVar[str] = "search_documents"
    description: ClassVar[str] = (
        "Search CRM documents by keyword in the current workspace. Read-only."
    )

    @classmethod
    def input_schema(cls) -> dict[str, Any]:
        return SearchDocumentsParams.model_json_schema()

    async def run(self, ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
        p = validate_args(params, SearchDocumentsParams)
        ws = ctx.auth.workspace_id
        q = {"workspace_id": ws, "q": p.query, "limit": min(p.limit, ctx.settings.tool_max_results)}
        key = ctx.cache.key_for(ws, self.name, q)
        hit = ctx.cache.get(key)
        if hit is not None:
            return hit
        resp = await ctx.client._request_with_retries(
            "GET", "/api/v1/documents/search", auth=ctx.auth, params=q
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
