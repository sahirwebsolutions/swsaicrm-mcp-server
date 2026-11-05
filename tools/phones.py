"""Workspace phone-number metadata — read only. Never dials."""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, Field

from middleware import ToolContext
from tools.base import BaseTool, ToolExecuteContext, validate_args


class ListWorkspacePhoneNumbersParams(BaseModel):
    model_config = {"extra": "forbid"}

    list_scope: str = Field(
        "outbound",
        max_length=32,
        description="outbound = caller-ID picker; management = admin list",
    )


class ListWorkspacePhoneNumbersTool(BaseTool):
    name: ClassVar[str] = "list_workspace_phone_numbers"
    description: ClassVar[str] = (
        "List workspace phone numbers and their status. Read-only metadata. "
        "Does not place calls. Workspace is taken from auth context."
    )

    @classmethod
    def input_schema(cls) -> dict[str, Any]:
        return ListWorkspacePhoneNumbersParams.model_json_schema()

    async def run(self, ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
        p = validate_args(params, ListWorkspacePhoneNumbersParams)
        ws = ctx.auth.workspace_id
        q = {"list_scope": p.list_scope or "outbound"}
        key = ctx.cache.key_for(ws, self.name, q)
        hit = ctx.cache.get(key)
        if hit is not None:
            return hit
        resp = await ctx.client._request_with_retries(
            "GET",
            f"/api/v1/phone-numbers/workspace/{ws}",
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
