"""Workspace member/user tools — FastAPI /api/v1/workspaces/{id}/members."""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, Field

from middleware import ToolContext
from tools.base import BaseTool, ToolExecuteContext, validate_args


class ListUsersParams(BaseModel):
    model_config = {"extra": "forbid"}

    page: int = Field(1, ge=1)
    limit: int = Field(50, ge=1, le=100)


class ListUsersTool(BaseTool):
    name: ClassVar[str] = "list_users"
    description: ClassVar[str] = (
        "Use when the user wants to see the people/team members in the workspace, or to "
        "find a member's id before assigning work or @-mentioning them. Returns human "
        "members (id, name, email, role). Read-only."
    )

    @classmethod
    def input_schema(cls) -> dict[str, Any]:
        return ListUsersParams.model_json_schema()

    async def run(self, ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
        p = validate_args(params, ListUsersParams)
        ws = ctx.auth.workspace_id
        max_lim = min(p.limit, ctx.settings.tool_max_results)
        key = ctx.cache.key_for(ws, self.name, {"page": p.page, "limit": max_lim})
        hit = ctx.cache.get(key)
        if hit is not None:
            return hit

        resp = await ctx.client._request_with_retries(
            "GET",
            f"/api/v1/workspaces/{ws}/members",
            auth=ctx.auth,
            params={"page": p.page, "limit": max_lim},
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
