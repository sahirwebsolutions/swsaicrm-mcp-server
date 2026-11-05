"""Call-log tools — FastAPI /api/v1/calls/recordings."""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, Field

from date_range import parse_relative_range
from middleware import ToolContext
from tools.base import BaseTool, ToolExecuteContext, validate_args


class ListCallsParams(BaseModel):
    model_config = {"extra": "forbid"}

    limit: int = Field(50, ge=1, le=300)
    offset: int = Field(0, ge=0)
    direction: str | None = Field(None, pattern="^(inbound|outbound)$")
    date_range: str | None = Field(
        None,
        max_length=64,
        description="Natural language range: 'today', 'last 7 days', 'this month', etc.",
    )
    date_from: str | None = Field(None, description="Explicit start date YYYY-MM-DD.")
    date_to: str | None = Field(None, description="Explicit end date YYYY-MM-DD.")


class ListCallsTool(BaseTool):
    name: ClassVar[str] = "list_calls"
    description: ClassVar[str] = (
        "Use when the user wants to see phone call logs/recordings, optionally by "
        "direction or date range (e.g. 'calls this week', 'outbound calls today'). "
        "Read-only."
    )

    @classmethod
    def input_schema(cls) -> dict[str, Any]:
        return ListCallsParams.model_json_schema()

    async def run(self, ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
        p = validate_args(params, ListCallsParams)
        ws = ctx.auth.workspace_id
        max_lim = min(p.limit, ctx.settings.tool_max_results)
        start, end = parse_relative_range(p.date_range, start=p.date_from, end=p.date_to)

        q: dict[str, Any] = {"workspace_id": ws, "limit": max_lim, "offset": p.offset}
        if p.direction:
            q["direction"] = p.direction
        if start:
            q["date_from"] = start
        if end:
            q["date_to"] = end

        key = ctx.cache.key_for(ws, self.name, q)
        hit = ctx.cache.get(key)
        if hit is not None:
            return hit

        resp = await ctx.client._request_with_retries(
            "GET", "/api/v1/calls/recordings", auth=ctx.auth, params=q
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
