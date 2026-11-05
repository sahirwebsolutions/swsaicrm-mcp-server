"""Inbox conversation reads — FastAPI /api/v1/inbox. Identity from auth only."""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, Field

from middleware import ToolContext
from tools.base import BaseTool, ToolExecuteContext, validate_args


class ListInboxConversationsParams(BaseModel):
    model_config = {"extra": "forbid"}

    channel: str | None = Field(None, max_length=32, description="email|whatsapp|call|sms")
    inbox_status: str | None = Field(None, max_length=32, description="inbox|assigned|draft|sent|closed")
    unread_only: bool = False
    limit: int = Field(20, ge=1, le=50)


class ListInboxConversationsTool(BaseTool):
    name: ClassVar[str] = "list_inbox_conversations"
    description: ClassVar[str] = (
        "List inbox conversations for the current workspace (email, WhatsApp, SMS, calls). "
        "Read-only. Workspace is taken from auth context."
    )

    @classmethod
    def input_schema(cls) -> dict[str, Any]:
        return ListInboxConversationsParams.model_json_schema()

    async def run(self, ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
        p = validate_args(params, ListInboxConversationsParams)
        ws = ctx.auth.workspace_id
        q: dict[str, Any] = {"workspace_id": ws, "limit": min(p.limit, ctx.settings.tool_max_results)}
        if p.channel:
            q["channel"] = p.channel
        if p.inbox_status:
            q["inbox_status"] = p.inbox_status
        if p.unread_only:
            q["unread_only"] = True
        key = ctx.cache.key_for(ws, self.name, q)
        hit = ctx.cache.get(key)
        if hit is not None:
            return hit
        resp = await ctx.client._request_with_retries(
            "GET", "/api/v1/inbox/conversations", auth=ctx.auth, params=q
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
