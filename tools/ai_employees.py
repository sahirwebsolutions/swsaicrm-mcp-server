"""Read-only AI Employee + mission tools — FastAPI only, no second business layer.

Identity comes from the caller's JWT. Do not accept workspace_id arguments.
"""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, Field

from middleware import ToolContext
from tools.base import BaseTool, ToolExecuteContext, validate_args


class ListAIEmployeesParams(BaseModel):
    model_config = {"extra": "forbid"}

    search: str | None = Field(None, max_length=120)
    is_active: bool | None = None
    limit: int = Field(50, ge=1, le=200)


class ListAIEmployeesTool(BaseTool):
    name: ClassVar[str] = "list_ai_employees"
    description: ClassVar[str] = (
        "List AI employees in the current workspace (name, role, autonomy, manager). "
        "Read-only. Workspace is taken from auth context."
    )

    @classmethod
    def input_schema(cls) -> dict[str, Any]:
        return ListAIEmployeesParams.model_json_schema()

    async def run(self, ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
        p = validate_args(params, ListAIEmployeesParams)
        q: dict[str, Any] = {"workspace_id": ctx.auth.workspace_id, "limit": p.limit}
        if p.search:
            q["search"] = p.search
        if p.is_active is not None:
            q["is_active"] = p.is_active
        resp = await ctx.client._request_with_retries(
            "GET", "/api/v1/ai-employees", auth=ctx.auth, params=q
        )
        body = ctx.client.raise_for_status(resp)
        te = ToolExecuteContext(
            user_id=ctx.auth.user_id,
            workspace_id=ctx.auth.workspace_id,
            request_id=ctx.request_id,
        )
        return self.wrap_result(body, te)


class ListAIEmployeeMissionsParams(BaseModel):
    model_config = {"extra": "forbid"}

    status: str | None = Field(None, max_length=40)
    limit: int = Field(50, ge=1, le=200)


class ListAIEmployeeMissionsTool(BaseTool):
    name: ClassVar[str] = "list_ai_employee_missions"
    description: ClassVar[str] = (
        "List durable AI employee missions for the current workspace. Read-only. "
        "Optional status filter: queued|running|waiting|needs_approval|completed|failed."
    )

    @classmethod
    def input_schema(cls) -> dict[str, Any]:
        return ListAIEmployeeMissionsParams.model_json_schema()

    async def run(self, ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
        p = validate_args(params, ListAIEmployeeMissionsParams)
        q: dict[str, Any] = {"workspace_id": ctx.auth.workspace_id}
        if p.status:
            q["status"] = p.status
        resp = await ctx.client._request_with_retries(
            "GET", "/api/v1/ai-employee-missions", auth=ctx.auth, params=q
        )
        body = ctx.client.raise_for_status(resp)
        rows = body.get("missions") if isinstance(body, dict) else body
        if isinstance(rows, list):
            body = {**(body if isinstance(body, dict) else {}), "missions": rows[: p.limit]}
        te = ToolExecuteContext(
            user_id=ctx.auth.user_id,
            workspace_id=ctx.auth.workspace_id,
            request_id=ctx.request_id,
        )
        return self.wrap_result(body, te)


class GetAIEmployeeMissionParams(BaseModel):
    model_config = {"extra": "forbid"}

    mission_id: str = Field(..., min_length=8, max_length=80)


class GetAIEmployeeMissionTool(BaseTool):
    name: ClassVar[str] = "get_ai_employee_mission"
    description: ClassVar[str] = (
        "Get one durable AI employee mission and its action trail. Read-only. "
        "Workspace isolation is enforced by the FastAPI endpoint."
    )

    @classmethod
    def input_schema(cls) -> dict[str, Any]:
        return GetAIEmployeeMissionParams.model_json_schema()

    async def run(self, ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
        p = validate_args(params, GetAIEmployeeMissionParams)
        resp = await ctx.client._request_with_retries(
            "GET",
            f"/api/v1/ai-employee-missions/{p.mission_id}",
            auth=ctx.auth,
            params={"workspace_id": ctx.auth.workspace_id},
        )
        body = ctx.client.raise_for_status(resp)
        te = ToolExecuteContext(
            user_id=ctx.auth.user_id,
            workspace_id=ctx.auth.workspace_id,
            request_id=ctx.request_id,
        )
        return self.wrap_result(body, te)
