"""Project tools — FastAPI /api/v1/projects. Distinct from deals/opportunities."""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, Field

from middleware import ToolContext
from tools.base import BaseTool, ToolExecuteContext, validate_args


class ListProjectsParams(BaseModel):
    model_config = {"extra": "forbid"}

    limit: int = Field(50, ge=1, le=100)
    page: int = Field(1, ge=1)
    status: str | None = Field(None, max_length=64)
    search: str | None = Field(None, max_length=512)


class ListProjectsTool(BaseTool):
    name: ClassVar[str] = "list_projects"
    description: ClassVar[str] = (
        "Use when the user wants to list, count, or filter PROJECTS from the Projects "
        "module (e.g. 'my projects', 'how many active projects'). Permission-scoped to "
        "the user. This is NOT deals/opportunities — use list_deals for those. Read-only."
    )

    @classmethod
    def input_schema(cls) -> dict[str, Any]:
        return ListProjectsParams.model_json_schema()

    async def run(self, ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
        p = validate_args(params, ListProjectsParams)
        ws = ctx.auth.workspace_id
        max_lim = min(p.limit, ctx.settings.tool_max_results)
        q: dict[str, Any] = {"workspace_id": ws, "page": p.page, "limit": max_lim}
        if p.status:
            q["status"] = p.status
        if p.search:
            q["search"] = p.search

        key = ctx.cache.key_for(ws, self.name, q)
        hit = ctx.cache.get(key)
        if hit is not None:
            return hit

        resp = await ctx.client._request_with_retries(
            "GET", "/api/v1/projects", auth=ctx.auth, params=q
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
