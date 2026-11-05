"""Discovery tools — resolve schema/config by keyword before acting.

These let the AI translate vague user words ("the budget field", "the Facebook source",
"the negotiation stage") into concrete ids/values before a create/update, instead of
guessing. All read-only.
"""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, Field

from middleware import ToolContext
from tools.base import BaseTool, ToolExecuteContext, validate_args


def _kw_match(hay: Any, needle: str) -> bool:
    return needle in str(hay or "").strip().lower()


class FindFieldParams(BaseModel):
    model_config = {"extra": "forbid"}

    keyword: str = Field(..., min_length=1, max_length=128)
    entity_type: str = Field(
        "contact", pattern="^(contact|deal|task|workforce_member)$"
    )


class ListLeadSourcesParams(BaseModel):
    model_config = {"extra": "forbid"}


class ListDealStagesParams(BaseModel):
    model_config = {"extra": "forbid"}


class FindCustomFieldTool(BaseTool):
    name: ClassVar[str] = "find_custom_field"
    description: ClassVar[str] = (
        "Use before setting a custom field to resolve the user's wording (e.g. 'budget', "
        "'industry') to a real custom-field definition (id, type, options) for contacts/"
        "deals/tasks. Read-only."
    )

    @classmethod
    def input_schema(cls) -> dict[str, Any]:
        return FindFieldParams.model_json_schema()

    async def run(self, ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
        p = validate_args(params, FindFieldParams)
        ws = ctx.auth.workspace_id
        key = ctx.cache.key_for(
            ws, self.name, {"keyword": p.keyword.lower(), "entity_type": p.entity_type}
        )
        hit = ctx.cache.get(key)
        if hit is not None:
            return hit

        resp = await ctx.client._request_with_retries(
            "GET",
            "/api/v1/custom-fields/definitions",
            auth=ctx.auth,
            params={"workspace_id": ws, "entity_type": p.entity_type},
        )
        body = ctx.client.raise_for_status(resp)
        defs = body if isinstance(body, list) else (body.get("data") or [])
        needle = p.keyword.strip().lower()
        matches = [
            {
                "id": d.get("id"),
                "name": d.get("name"),
                "field_type": d.get("field_type"),
                "options": d.get("options"),
                "entity_type": d.get("entity_type"),
            }
            for d in defs
            if isinstance(d, dict)
            and (_kw_match(d.get("name"), needle) or _kw_match(d.get("description"), needle))
        ]
        te = ToolExecuteContext(
            user_id=ctx.auth.user_id,
            workspace_id=ctx.auth.workspace_id,
            request_id=ctx.request_id,
        )
        out = self.wrap_result({"count": len(matches), "fields": matches}, te)
        ctx.cache.set(key, out)
        return out


class ListLeadSourcesTool(BaseTool):
    name: ClassVar[str] = "list_lead_sources"
    description: ClassVar[str] = (
        "Use to see the configured lead/contact sources, or to resolve a source name "
        "before filtering/creating a contact. Read-only."
    )

    @classmethod
    def input_schema(cls) -> dict[str, Any]:
        return ListLeadSourcesParams.model_json_schema()

    async def run(self, ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
        validate_args(params, ListLeadSourcesParams)
        ws = ctx.auth.workspace_id
        key = ctx.cache.key_for(ws, self.name, {})
        hit = ctx.cache.get(key)
        if hit is not None:
            return hit

        resp = await ctx.client._request_with_retries(
            "GET",
            "/api/v1/contacts/lead-sources",
            auth=ctx.auth,
            params={"workspace_id": ws},
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


class ListDealStagesTool(BaseTool):
    name: ClassVar[str] = "list_deal_stages"
    description: ClassVar[str] = (
        "Use to see the deal/opportunity pipeline stages, or to resolve a stage name "
        "before creating/moving a deal. Read-only."
    )

    @classmethod
    def input_schema(cls) -> dict[str, Any]:
        return ListDealStagesParams.model_json_schema()

    async def run(self, ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
        validate_args(params, ListDealStagesParams)
        ws = ctx.auth.workspace_id
        key = ctx.cache.key_for(ws, self.name, {})
        hit = ctx.cache.get(key)
        if hit is not None:
            return hit

        resp = await ctx.client._request_with_retries(
            "GET",
            "/api/v1/opportunities/stages",
            auth=ctx.auth,
            params={"workspace_id": ws},
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
