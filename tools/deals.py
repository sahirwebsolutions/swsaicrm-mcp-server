"""Deals / pipelines — FastAPI /api/v1/opportunities (opportunities + stages)."""

from __future__ import annotations

from typing import Any, ClassVar
from uuid import UUID

from pydantic import BaseModel, Field

from idempotency_keys import compute_idempotency_key, compute_stable_update_idempotency_key
from middleware import ToolContext
from tool_logging import log_write_tool_invoked
from tools.base import BaseTool, ToolExecuteContext, validate_args
from write_helpers import finalize_write_success, guard_try_cached


class ListPipelinesParams(BaseModel):
    model_config = {"extra": "forbid"}

    assigned_to: str | None = Field(None, max_length=200)


class ListPipelinesTool(BaseTool):
    name: ClassVar[str] = "list_pipelines"
    description: ClassVar[str] = (
        "Use when the user wants to see the sales pipeline — stages and the deals within "
        "each (e.g. 'show me the pipeline', 'what's in each stage'). Read-only."
    )

    @classmethod
    def input_schema(cls) -> dict[str, Any]:
        return ListPipelinesParams.model_json_schema()

    async def run(self, ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
        p = validate_args(params, ListPipelinesParams)
        ws = ctx.auth.workspace_id
        key = ctx.cache.key_for(
            ws,
            self.name,
            {"assigned_to": p.assigned_to},
        )
        hit = ctx.cache.get(key)
        if hit is not None:
            return hit

        q: dict[str, Any] = {"workspace_id": ws}
        if p.assigned_to is not None:
            q["assigned_to"] = p.assigned_to

        resp = await ctx.client._request_with_retries(
            "GET",
            "/api/v1/opportunities/pipeline",
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


class CreatePipelineParams(BaseModel):
    model_config = {"extra": "forbid"}

    name: str = Field(..., min_length=1, max_length=255)
    description: str = Field("", max_length=2000)
    probability: int = Field(0, ge=0, le=100)
    stage_order: int = 0
    is_closed: bool = False
    is_won: bool = False
    color: str | None = Field(None, max_length=32)


class CreatePipelineTool(BaseTool):
    name: ClassVar[str] = "create_pipeline"
    description: ClassVar[str] = (
        "Use when the user wants to add a new pipeline/opportunity stage to the sales process."
    )

    @classmethod
    def input_schema(cls) -> dict[str, Any]:
        return CreatePipelineParams.model_json_schema()

    async def run(self, ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
        p = validate_args(params, CreatePipelineParams)
        if ctx.settings.dry_run:
            te = ToolExecuteContext(
                user_id=ctx.auth.user_id,
                workspace_id=ctx.auth.workspace_id,
                request_id=ctx.request_id,
            )
            return self.wrap_result({"dry_run": True}, te)

        ws = ctx.auth.workspace_id
        snap = p.model_dump(mode="json")
        dup = guard_try_cached(ctx, self.name, ws, snap)
        if dup is not None:
            return dup

        idem = compute_idempotency_key(ws, self.name, self.version, snap)

        body: dict[str, Any] = {
            "name": p.name,
            "description": p.description,
            "probability": p.probability,
            "stage_order": p.stage_order,
            "is_closed": p.is_closed,
            "is_won": p.is_won,
        }
        if p.color is not None:
            body["color"] = p.color

        try:
            resp = await ctx.client._request_with_retries(
                "POST",
                "/api/v1/opportunities/stages",
                auth=ctx.auth,
                params={"workspace_id": ws},
                json_body=body,
                idempotency_key=idem,
            )
            out_body = ctx.client.raise_for_status(resp)
            log_write_tool_invoked(
                tool=self.name,
                idempotency_key=idem,
                request_id=ctx.request_id,
                status="success",
                outcome_body=out_body if isinstance(out_body, dict) else None,
            )
        except Exception:
            log_write_tool_invoked(
                tool=self.name,
                idempotency_key=idem,
                request_id=ctx.request_id,
                status="error",
            )
            raise

        te = ToolExecuteContext(
            user_id=ctx.auth.user_id,
            workspace_id=ctx.auth.workspace_id,
            request_id=ctx.request_id,
        )
        wrapped = self.wrap_result(out_body, te)
        finalize_write_success(
            ctx,
            self.name,
            ws,
            snap,
            wrapped,
            idem,
            out_body if isinstance(out_body, dict) else {},
        )
        return wrapped


class UpdatePipelineParams(BaseModel):
    model_config = {"extra": "forbid"}

    pipeline_id: UUID
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = Field(None, max_length=2000)
    probability: int | None = Field(None, ge=0, le=100)
    stage_order: int | None = None
    is_closed: bool | None = None
    is_won: bool | None = None
    color: str | None = Field(None, max_length=32)


class UpdatePipelineTool(BaseTool):
    name: ClassVar[str] = "update_pipeline"
    description: ClassVar[str] = (
        "Use when the user wants to rename or reconfigure an existing pipeline/opportunity stage."
    )

    @classmethod
    def input_schema(cls) -> dict[str, Any]:
        return UpdatePipelineParams.model_json_schema()

    async def run(self, ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
        p = validate_args(params, UpdatePipelineParams)
        if ctx.settings.dry_run:
            te = ToolExecuteContext(
                user_id=ctx.auth.user_id,
                workspace_id=ctx.auth.workspace_id,
                request_id=ctx.request_id,
            )
            return self.wrap_result({"dry_run": True}, te)

        ws = ctx.auth.workspace_id
        snap = p.model_dump(mode="json")
        dup = guard_try_cached(ctx, self.name, ws, snap)
        if dup is not None:
            return dup

        idem = compute_stable_update_idempotency_key(
            ws, self.name, self.version, str(p.pipeline_id), "update_fields"
        )

        patch: dict[str, Any] = {}
        if p.name is not None:
            patch["name"] = p.name
        if p.description is not None:
            patch["description"] = p.description
        if p.probability is not None:
            patch["probability"] = p.probability
        if p.stage_order is not None:
            patch["stage_order"] = p.stage_order
        if p.is_closed is not None:
            patch["is_closed"] = p.is_closed
        if p.is_won is not None:
            patch["is_won"] = p.is_won
        if p.color is not None:
            patch["color"] = p.color
        if not patch:
            raise ValueError("At least one field must be provided")

        path = f"/api/v1/opportunities/stages/{p.pipeline_id}"
        try:
            resp = await ctx.client._request_with_retries(
                "PUT",
                path,
                auth=ctx.auth,
                params={"workspace_id": ws},
                json_body=patch,
                idempotency_key=idem,
            )
            out_body = ctx.client.raise_for_status(resp)
            log_write_tool_invoked(
                tool=self.name,
                idempotency_key=idem,
                request_id=ctx.request_id,
                status="success",
                outcome_body=out_body if isinstance(out_body, dict) else None,
            )
        except Exception:
            log_write_tool_invoked(
                tool=self.name,
                idempotency_key=idem,
                request_id=ctx.request_id,
                status="error",
            )
            raise

        te = ToolExecuteContext(
            user_id=ctx.auth.user_id,
            workspace_id=ctx.auth.workspace_id,
            request_id=ctx.request_id,
        )
        wrapped = self.wrap_result(out_body, te)
        finalize_write_success(
            ctx,
            self.name,
            ws,
            snap,
            wrapped,
            idem,
            out_body if isinstance(out_body, dict) else {},
        )
        return wrapped


class ListDealsParams(BaseModel):
    model_config = {"extra": "forbid"}

    stage: str | None = Field(None, max_length=100)
    status: str | None = Field(None, max_length=50)
    assigned_to: str | None = Field(None, max_length=200)
    search: str | None = Field(None, max_length=512)
    page: int = Field(1, ge=1, le=10000)
    limit: int = Field(20, ge=1, le=100)
    sort_by: str = Field("created_at", max_length=64)
    sort_order: str = Field("desc", pattern=r"^(?i)(asc|desc)$")


class ListDealsTool(BaseTool):
    name: ClassVar[str] = "list_deals"
    description: ClassVar[str] = (
        "Use when the user wants to list, count, or filter deals/opportunities (sales "
        "pipeline). Not for Projects — use projects tools for those. Read-only."
    )

    @classmethod
    def input_schema(cls) -> dict[str, Any]:
        return ListDealsParams.model_json_schema()

    async def run(self, ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
        p = validate_args(params, ListDealsParams)
        ws = ctx.auth.workspace_id
        key = ctx.cache.key_for(
            ws,
            self.name,
            {
                "stage": p.stage,
                "status": p.status,
                "assigned_to": p.assigned_to,
                "search": p.search,
                "page": p.page,
                "limit": p.limit,
                "sort_by": p.sort_by,
                "sort_order": p.sort_order.lower(),
            },
        )
        hit = ctx.cache.get(key)
        if hit is not None:
            return hit

        q: dict[str, Any] = {
            "workspace_id": ws,
            "page": p.page,
            "limit": min(p.limit, ctx.settings.tool_max_results),
            "sort_by": p.sort_by,
            "sort_order": p.sort_order.lower(),
        }
        if p.stage is not None:
            q["stage"] = p.stage
        if p.status is not None:
            q["status"] = p.status
        if p.assigned_to is not None:
            q["assigned_to"] = p.assigned_to
        if p.search is not None:
            q["search"] = p.search

        resp = await ctx.client._request_with_retries(
            "GET",
            "/api/v1/opportunities/",
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


class CreateDealParams(BaseModel):
    model_config = {"extra": "forbid"}

    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(None, max_length=5000)
    value: float = Field(0, ge=0)
    currency: str = Field("USD", max_length=8)
    stage: str | None = Field(None, max_length=100)
    probability: int = Field(0, ge=0, le=100)
    primary_contact_id: UUID | None = None


class CreateDealTool(BaseTool):
    name: ClassVar[str] = "create_deal"
    description: ClassVar[str] = (
        "Use when the user wants to add a new deal or opportunity to the sales pipeline."
    )

    @classmethod
    def input_schema(cls) -> dict[str, Any]:
        return CreateDealParams.model_json_schema()

    async def run(self, ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
        p = validate_args(params, CreateDealParams)
        if ctx.settings.dry_run:
            te = ToolExecuteContext(
                user_id=ctx.auth.user_id,
                workspace_id=ctx.auth.workspace_id,
                request_id=ctx.request_id,
            )
            return self.wrap_result({"dry_run": True}, te)

        ws = ctx.auth.workspace_id
        snap = p.model_dump(mode="json")
        dup = guard_try_cached(ctx, self.name, ws, snap)
        if dup is not None:
            return dup

        idem_payload = {k: v for k, v in snap.items() if v is not None}
        idem = compute_idempotency_key(ws, self.name, self.version, idem_payload)

        body: dict[str, Any] = {
            "name": p.name,
            "value": p.value,
            "currency": p.currency,
            "probability": p.probability,
        }
        if p.description is not None:
            body["description"] = p.description
        if p.stage is not None:
            body["stage"] = p.stage
        if p.primary_contact_id is not None:
            body["primary_contact_id"] = str(p.primary_contact_id)

        try:
            resp = await ctx.client._request_with_retries(
                "POST",
                "/api/v1/opportunities/",
                auth=ctx.auth,
                params={"workspace_id": ws},
                json_body=body,
                idempotency_key=idem,
            )
            out_body = ctx.client.raise_for_status(resp)
            log_write_tool_invoked(
                tool=self.name,
                idempotency_key=idem,
                request_id=ctx.request_id,
                status="success",
                outcome_body=out_body if isinstance(out_body, dict) else None,
            )
        except Exception:
            log_write_tool_invoked(
                tool=self.name,
                idempotency_key=idem,
                request_id=ctx.request_id,
                status="error",
            )
            raise

        te = ToolExecuteContext(
            user_id=ctx.auth.user_id,
            workspace_id=ctx.auth.workspace_id,
            request_id=ctx.request_id,
        )
        wrapped = self.wrap_result(out_body, te)
        finalize_write_success(
            ctx,
            self.name,
            ws,
            snap,
            wrapped,
            idem,
            out_body if isinstance(out_body, dict) else {},
        )
        return wrapped


class UpdateDealStageParams(BaseModel):
    model_config = {"extra": "forbid"}

    deal_id: UUID
    stage: str = Field(..., min_length=1, max_length=100)


class UpdateDealStageTool(BaseTool):
    name: ClassVar[str] = "update_deal_stage"
    description: ClassVar[str] = (
        "Use when the user wants to move/advance a deal to a different pipeline stage "
        "(e.g. 'move this deal to Negotiation', 'mark it won')."
    )

    @classmethod
    def input_schema(cls) -> dict[str, Any]:
        return UpdateDealStageParams.model_json_schema()

    async def run(self, ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
        p = validate_args(params, UpdateDealStageParams)
        if ctx.settings.dry_run:
            te = ToolExecuteContext(
                user_id=ctx.auth.user_id,
                workspace_id=ctx.auth.workspace_id,
                request_id=ctx.request_id,
            )
            return self.wrap_result({"dry_run": True}, te)

        ws = ctx.auth.workspace_id
        snap = p.model_dump(mode="json")
        dup = guard_try_cached(ctx, self.name, ws, snap)
        if dup is not None:
            return dup

        idem = compute_stable_update_idempotency_key(
            ws, self.name, self.version, str(p.deal_id), "update_stage"
        )

        path = f"/api/v1/opportunities/{p.deal_id}"
        try:
            resp = await ctx.client._request_with_retries(
                "PUT",
                path,
                auth=ctx.auth,
                params={"workspace_id": ws},
                json_body={"stage": p.stage},
                idempotency_key=idem,
            )
            out_body = ctx.client.raise_for_status(resp)
            log_write_tool_invoked(
                tool=self.name,
                idempotency_key=idem,
                request_id=ctx.request_id,
                status="success",
                outcome_body=out_body if isinstance(out_body, dict) else None,
            )
        except Exception:
            log_write_tool_invoked(
                tool=self.name,
                idempotency_key=idem,
                request_id=ctx.request_id,
                status="error",
            )
            raise

        te = ToolExecuteContext(
            user_id=ctx.auth.user_id,
            workspace_id=ctx.auth.workspace_id,
            request_id=ctx.request_id,
        )
        wrapped = self.wrap_result(out_body, te)
        finalize_write_success(
            ctx,
            self.name,
            ws,
            snap,
            wrapped,
            idem,
            out_body if isinstance(out_body, dict) else {},
        )
        return wrapped


class UpdateDealParams(BaseModel):
    model_config = {"extra": "forbid"}

    deal_id: UUID
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = Field(None, max_length=5000)
    value: float | None = Field(None, ge=0)
    currency: str | None = Field(None, max_length=8)
    stage: str | None = Field(None, max_length=100)
    probability: int | None = Field(None, ge=0, le=100)
    status: str | None = Field(None, max_length=50)
    primary_contact_id: UUID | None = None


class UpdateDealTool(BaseTool):
    name: ClassVar[str] = "update_deal"
    description: ClassVar[str] = (
        "Use when the user wants to change a deal's fields — value, name, status, close "
        "date, etc. To only move stages, prefer update_deal_stage."
    )

    @classmethod
    def input_schema(cls) -> dict[str, Any]:
        return UpdateDealParams.model_json_schema()

    async def run(self, ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
        p = validate_args(params, UpdateDealParams)
        if ctx.settings.dry_run:
            te = ToolExecuteContext(
                user_id=ctx.auth.user_id,
                workspace_id=ctx.auth.workspace_id,
                request_id=ctx.request_id,
            )
            return self.wrap_result({"dry_run": True}, te)

        ws = ctx.auth.workspace_id
        snap = p.model_dump(mode="json")
        dup = guard_try_cached(ctx, self.name, ws, snap)
        if dup is not None:
            return dup

        idem = compute_stable_update_idempotency_key(
            ws, self.name, self.version, str(p.deal_id), "update_fields"
        )

        patch: dict[str, Any] = {}
        if p.name is not None:
            patch["name"] = p.name
        if p.description is not None:
            patch["description"] = p.description
        if p.value is not None:
            patch["value"] = p.value
        if p.currency is not None:
            patch["currency"] = p.currency
        if p.stage is not None:
            patch["stage"] = p.stage
        if p.probability is not None:
            patch["probability"] = p.probability
        if p.status is not None:
            patch["status"] = p.status
        if p.primary_contact_id is not None:
            patch["primary_contact_id"] = str(p.primary_contact_id)
        if not patch:
            raise ValueError("At least one field must be provided")

        path = f"/api/v1/opportunities/{p.deal_id}"
        try:
            resp = await ctx.client._request_with_retries(
                "PUT",
                path,
                auth=ctx.auth,
                params={"workspace_id": ws},
                json_body=patch,
                idempotency_key=idem,
            )
            out_body = ctx.client.raise_for_status(resp)
            log_write_tool_invoked(
                tool=self.name,
                idempotency_key=idem,
                request_id=ctx.request_id,
                status="success",
                outcome_body=out_body if isinstance(out_body, dict) else None,
            )
        except Exception:
            log_write_tool_invoked(
                tool=self.name,
                idempotency_key=idem,
                request_id=ctx.request_id,
                status="error",
            )
            raise

        te = ToolExecuteContext(
            user_id=ctx.auth.user_id,
            workspace_id=ctx.auth.workspace_id,
            request_id=ctx.request_id,
        )
        wrapped = self.wrap_result(out_body, te)
        finalize_write_success(
            ctx,
            self.name,
            ws,
            snap,
            wrapped,
            idem,
            out_body if isinstance(out_body, dict) else {},
        )
        return wrapped


class DeleteDealParams(BaseModel):
    model_config = {"extra": "forbid"}

    deal_id: UUID


class DeleteDealTool(BaseTool):
    name: ClassVar[str] = "delete_deal"
    description: ClassVar[str] = (
        "Use ONLY when the user explicitly asks to delete or remove a deal/opportunity. "
        "Destructive and irreversible — confirm intent first."
    )

    @classmethod
    def input_schema(cls) -> dict[str, Any]:
        return DeleteDealParams.model_json_schema()

    async def run(self, ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
        p = validate_args(params, DeleteDealParams)
        if ctx.settings.dry_run:
            te = ToolExecuteContext(
                user_id=ctx.auth.user_id,
                workspace_id=ctx.auth.workspace_id,
                request_id=ctx.request_id,
            )
            return self.wrap_result({"dry_run": True}, te)

        ws = ctx.auth.workspace_id
        snap = p.model_dump(mode="json")
        dup = guard_try_cached(ctx, self.name, ws, snap)
        if dup is not None:
            return dup

        idem = compute_stable_update_idempotency_key(
            ws, self.name, self.version, str(p.deal_id), "delete"
        )

        path = f"/api/v1/opportunities/{p.deal_id}"
        try:
            resp = await ctx.client._request_with_retries(
                "DELETE",
                path,
                auth=ctx.auth,
                params={"workspace_id": ws},
                idempotency_key=idem,
            )
            out_body = ctx.client.raise_for_status(resp)
            log_write_tool_invoked(
                tool=self.name,
                idempotency_key=idem,
                request_id=ctx.request_id,
                status="success",
                outcome_body=out_body if isinstance(out_body, dict) else None,
            )
        except Exception:
            log_write_tool_invoked(
                tool=self.name,
                idempotency_key=idem,
                request_id=ctx.request_id,
                status="error",
            )
            raise

        te = ToolExecuteContext(
            user_id=ctx.auth.user_id,
            workspace_id=ctx.auth.workspace_id,
            request_id=ctx.request_id,
        )
        wrapped = self.wrap_result(out_body, te)
        finalize_write_success(
            ctx,
            self.name,
            ws,
            snap,
            wrapped,
            idem,
            out_body if isinstance(out_body, dict) else {},
        )
        return wrapped
