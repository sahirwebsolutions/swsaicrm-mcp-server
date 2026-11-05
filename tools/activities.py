"""Activity timeline tools — FastAPI /api/v1/contacts/{id}/timeline."""

from __future__ import annotations

from typing import Any, ClassVar
from uuid import UUID

from pydantic import BaseModel, Field

from middleware import ToolContext
from tools.base import BaseTool, ToolExecuteContext, validate_args


class ListActivitiesParams(BaseModel):
    model_config = {"extra": "forbid"}

    contact_id: UUID
    limit: int = Field(20, ge=1, le=100)
    event_type: str | None = Field(
        None,
        max_length=64,
        description="Optional filter, e.g. CALL, WHATSAPP, EMAIL, STATUS_CHANGED.",
    )


class ListActivitiesTool(BaseTool):
    name: ClassVar[str] = "list_activities"
    description: ClassVar[str] = (
        "Use when the user wants the activity history/timeline for a specific contact "
        "(calls, messages, status changes) — you must have the contact_id. Read-only."
    )

    @classmethod
    def input_schema(cls) -> dict[str, Any]:
        return ListActivitiesParams.model_json_schema()

    async def run(self, ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
        p = validate_args(params, ListActivitiesParams)
        ws = ctx.auth.workspace_id
        max_lim = min(p.limit, ctx.settings.tool_max_results)
        q: dict[str, Any] = {"workspace_id": ws, "limit": max_lim}
        if p.event_type:
            q["event_type"] = p.event_type

        key = ctx.cache.key_for(
            ws, self.name, {"contact_id": str(p.contact_id), **q}
        )
        hit = ctx.cache.get(key)
        if hit is not None:
            return hit

        resp = await ctx.client._request_with_retries(
            "GET",
            f"/api/v1/contacts/{p.contact_id}/timeline",
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
