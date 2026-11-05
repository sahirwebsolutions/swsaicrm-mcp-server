"""Identity tools — who is the current user + which workspace am I acting in.

Backed by FastAPI ``GET /api/v1/auth/me`` using the caller's own JWT. This is the
anchor the AI needs to correctly resolve first-person requests like "my tasks",
"deals assigned to me", or "projects I'm part of" — it turns "me" into a real id.
"""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel

from middleware import ToolContext
from tools.base import BaseTool, ToolExecuteContext, validate_args


class WhoAmIParams(BaseModel):
    model_config = {"extra": "forbid"}


class WhoAmITool(BaseTool):
    name: ClassVar[str] = "whoami"
    description: ClassVar[str] = (
        "Use to identify the current user and active workspace before answering "
        "first-person requests like 'my tasks', 'deals assigned to me', or 'projects "
        "I'm part of'. Returns the caller's profile (id, name, email) and workspace id. "
        "Read-only."
    )

    @classmethod
    def input_schema(cls) -> dict[str, Any]:
        return WhoAmIParams.model_json_schema()

    async def run(self, ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
        validate_args(params, WhoAmIParams)
        resp = await ctx.client._request_with_retries(
            "GET", "/api/v1/auth/me", auth=ctx.auth
        )
        body = ctx.client.raise_for_status(resp)
        te = ToolExecuteContext(
            user_id=ctx.auth.user_id,
            workspace_id=ctx.auth.workspace_id,
            request_id=ctx.request_id,
        )
        data = {
            "user": body,
            "user_id": ctx.auth.user_id,
            "workspace_id": ctx.auth.workspace_id,
        }
        return self.wrap_result(data, te)


class GetMeTool(WhoAmITool):
    """Alias for clients familiar with the ``get_me`` naming convention."""

    name: ClassVar[str] = "get_me"
    description: ClassVar[str] = (
        "Alias of `whoami`. Returns the current user's profile and the active "
        "workspace id — use to resolve 'me'/'my' before first-person queries. Read-only."
    )
