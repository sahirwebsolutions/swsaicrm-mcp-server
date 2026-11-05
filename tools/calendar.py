"""Calendar / appointment tools — FastAPI /api/v1/calendar/events."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from date_range import parse_relative_range
from middleware import ToolContext
from tools.base import BaseTool, ToolExecuteContext, validate_args


class ListAppointmentsParams(BaseModel):
    model_config = {"extra": "forbid"}

    date_range: str | None = Field(
        None,
        max_length=64,
        description="Natural language range: 'today', 'this week', 'next 7 days', etc. "
        "Defaults to the next 30 days if omitted.",
    )
    date_from: str | None = Field(None, description="Explicit start date YYYY-MM-DD.")
    date_to: str | None = Field(None, description="Explicit end date YYYY-MM-DD.")
    only_mine: bool = False


class ListAppointmentsTool(BaseTool):
    name: ClassVar[str] = "list_appointments"
    description: ClassVar[str] = (
        "Use when the user wants to see calendar events/appointments/meetings in a date "
        "window (e.g. 'my meetings today', 'appointments this week'). Read-only."
    )

    @classmethod
    def input_schema(cls) -> dict[str, Any]:
        return ListAppointmentsParams.model_json_schema()

    async def run(self, ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
        p = validate_args(params, ListAppointmentsParams)
        ws = ctx.auth.workspace_id
        start, end = parse_relative_range(p.date_range, start=p.date_from, end=p.date_to)

        # The calendar endpoint requires an explicit window; default to next 30 days.
        today = datetime.now(timezone.utc).date()
        if not start:
            start = today.isoformat()
        if not end:
            end = (today + timedelta(days=30)).isoformat()

        q: dict[str, Any] = {
            "workspace_id": ws,
            "start": f"{start}T00:00:00Z",
            "end": f"{end}T23:59:59Z",
            "only_mine": p.only_mine,
        }

        key = ctx.cache.key_for(ws, self.name, q)
        hit = ctx.cache.get(key)
        if hit is not None:
            return hit

        resp = await ctx.client._request_with_retries(
            "GET", "/api/v1/calendar/events", auth=ctx.auth, params=q
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
