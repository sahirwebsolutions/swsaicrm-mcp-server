"""Universal Report Builder tools — FastAPI /api/v1/report-builder + /api/v1/custom-reports.

DSL-only. The AI may list registries and create/update/validate/preview/publish report
definitions. No SQL, no React, no arbitrary queries. Existing generate_report whitelist
stays in tools/reporting.py.
"""

from __future__ import annotations

from typing import Any, ClassVar
from uuid import UUID

from pydantic import BaseModel, Field

from middleware import ToolContext
from tools.base import BaseTool, ToolExecuteContext, validate_args


class _EmptyParams(BaseModel):
    model_config = {"extra": "forbid"}


class DescribeDatasetParams(BaseModel):
    model_config = {"extra": "forbid"}

    dataset_id: str = Field(..., min_length=1, max_length=64)


class CreateReportParams(BaseModel):
    model_config = {"extra": "forbid"}

    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(None, max_length=2000)
    scope: str = Field("workspace", max_length=32)
    definition: dict[str, Any] | None = None


class UpdateReportParams(BaseModel):
    model_config = {"extra": "forbid"}

    report_id: UUID
    name: str | None = Field(None, max_length=200)
    description: str | None = Field(None, max_length=2000)
    scope: str | None = Field(None, max_length=32)
    definition: dict[str, Any] | None = None


class MoveComponentParams(BaseModel):
    model_config = {"extra": "forbid"}

    report_id: UUID
    component_id: str = Field(..., min_length=1, max_length=64)
    x: int | None = Field(None, ge=0)
    y: int | None = Field(None, ge=0)
    w: int | None = Field(None, ge=1, le=12)
    h: int | None = Field(None, ge=1)


class ValidateReportParams(BaseModel):
    model_config = {"extra": "forbid"}

    definition: dict[str, Any] | None = None
    report_id: UUID | None = None


class PreviewReportParams(BaseModel):
    model_config = {"extra": "forbid"}

    definition: dict[str, Any] | None = None
    report_id: UUID | None = None
    context: dict[str, Any] | None = None


class PublishReportParams(BaseModel):
    model_config = {"extra": "forbid"}

    report_id: UUID
    version_id: UUID | None = None


def _te(ctx: ToolContext) -> ToolExecuteContext:
    return ToolExecuteContext(
        user_id=ctx.auth.user_id,
        workspace_id=ctx.auth.workspace_id,
        request_id=ctx.request_id,
    )


class ListReportDatasetsTool(BaseTool):
    name: ClassVar[str] = "list_report_datasets"
    description: ClassVar[str] = (
        "List Universal Report Builder datasets (projects, tasks, contacts, and other "
        "registered sources). Use before creating a custom report. Read-only."
    )

    @classmethod
    def input_schema(cls) -> dict[str, Any]:
        return _EmptyParams.model_json_schema()

    async def run(self, ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
        validate_args(params, _EmptyParams)
        ws = ctx.auth.workspace_id
        resp = await ctx.client._request_with_retries(
            "GET",
            "/api/v1/report-builder/datasets",
            auth=ctx.auth,
            params={"workspace_id": ws},
        )
        return self.wrap_result(ctx.client.raise_for_status(resp), _te(ctx))


class DescribeReportDatasetTool(BaseTool):
    name: ClassVar[str] = "describe_report_dataset"
    description: ClassVar[str] = (
        "Describe one Universal Report Builder dataset including metrics, dimensions, "
        "and allowed filters. Read-only. Do not invent metrics that are not listed."
    )

    @classmethod
    def input_schema(cls) -> dict[str, Any]:
        return DescribeDatasetParams.model_json_schema()

    async def run(self, ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
        p = validate_args(params, DescribeDatasetParams)
        resp = await ctx.client._request_with_retries(
            "GET",
            f"/api/v1/report-builder/datasets/{p.dataset_id}",
            auth=ctx.auth,
            params={"workspace_id": ctx.auth.workspace_id},
        )
        return self.wrap_result(ctx.client.raise_for_status(resp), _te(ctx))


class ListReportComponentsTool(BaseTool):
    name: ClassVar[str] = "list_report_components"
    description: ClassVar[str] = (
        "List Universal Report Builder component types (kpi, charts, table, text). "
        "Use these types only when composing a definition. Read-only."
    )

    @classmethod
    def input_schema(cls) -> dict[str, Any]:
        return _EmptyParams.model_json_schema()

    async def run(self, ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
        validate_args(params, _EmptyParams)
        resp = await ctx.client._request_with_retries(
            "GET",
            "/api/v1/report-builder/components",
            auth=ctx.auth,
            params={"workspace_id": ctx.auth.workspace_id},
        )
        return self.wrap_result(ctx.client.raise_for_status(resp), _te(ctx))


class CreateReportTool(BaseTool):
    name: ClassVar[str] = "create_report"
    description: ClassVar[str] = (
        "Create a Universal Report Builder draft from a report DSL JSON. No SQL, no "
        "JavaScript, no React. Use list_report_datasets and list_report_components first."
    )

    @classmethod
    def input_schema(cls) -> dict[str, Any]:
        return CreateReportParams.model_json_schema()

    async def run(self, ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
        p = validate_args(params, CreateReportParams)
        if ctx.settings.dry_run:
            return self.wrap_result({"dry_run": True, "would_create": True}, _te(ctx))
        body: dict[str, Any] = {
            "workspace_id": ctx.auth.workspace_id,
            "name": p.name,
            "scope": p.scope,
        }
        if p.description:
            body["description"] = p.description
        if p.definition:
            body["definition"] = p.definition
        resp = await ctx.client._request_with_retries(
            "POST",
            "/api/v1/custom-reports",
            auth=ctx.auth,
            json_body=body,
        )
        return self.wrap_result(ctx.client.raise_for_status(resp), _te(ctx))


class UpdateReportTool(BaseTool):
    name: ClassVar[str] = "update_report"
    description: ClassVar[str] = (
        "Update a custom report draft. Pass a full DSL definition to replace the canvas, "
        "and/or name/description/scope. No SQL or executable code."
    )

    @classmethod
    def input_schema(cls) -> dict[str, Any]:
        return UpdateReportParams.model_json_schema()

    async def run(self, ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
        p = validate_args(params, UpdateReportParams)
        if ctx.settings.dry_run:
            return self.wrap_result({"dry_run": True, "would_update": True}, _te(ctx))
        ws = ctx.auth.workspace_id
        out: dict[str, Any] = {}
        meta = {k: v for k, v in (("name", p.name), ("description", p.description), ("scope", p.scope)) if v is not None}
        if meta:
            resp = await ctx.client._request_with_retries(
                "PATCH",
                f"/api/v1/custom-reports/{p.report_id}",
                auth=ctx.auth,
                params={"workspace_id": ws},
                json_body=meta,
            )
            out["report"] = ctx.client.raise_for_status(resp)
        if p.definition is not None:
            resp = await ctx.client._request_with_retries(
                "POST",
                f"/api/v1/custom-reports/{p.report_id}/versions",
                auth=ctx.auth,
                params={"workspace_id": ws},
                json_body={"definition": p.definition},
            )
            out["draft"] = ctx.client.raise_for_status(resp)
        if not out:
            raise ValueError("Provide definition and/or name, description, scope")
        return self.wrap_result(out, _te(ctx))


class MoveReportComponentTool(BaseTool):
    name: ClassVar[str] = "move_report_component"
    description: ClassVar[str] = (
        "Move or resize one component on a custom report draft (12-column grid). "
        "Loads the current draft, updates layout, and saves. No SQL."
    )

    @classmethod
    def input_schema(cls) -> dict[str, Any]:
        return MoveComponentParams.model_json_schema()

    async def run(self, ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
        p = validate_args(params, MoveComponentParams)
        if ctx.settings.dry_run:
            return self.wrap_result({"dry_run": True, "would_move": True}, _te(ctx))
        ws = ctx.auth.workspace_id
        report_resp = await ctx.client._request_with_retries(
            "GET",
            f"/api/v1/custom-reports/{p.report_id}",
            auth=ctx.auth,
            params={"workspace_id": ws},
        )
        report = ctx.client.raise_for_status(report_resp)
        versions = ((report.get("data") or report) if isinstance(report, dict) else {}).get("versions") or []
        draft = next((v for v in versions if v.get("status") == "draft"), None)
        if draft is None and versions:
            draft = versions[0]
        definition = dict((draft or {}).get("definition") or {})
        found = False
        for item in definition.get("components") or []:
            if isinstance(item, dict) and item.get("id") == p.component_id:
                layout = dict(item.get("layout") or {})
                if p.x is not None:
                    layout["x"] = p.x
                if p.y is not None:
                    layout["y"] = p.y
                if p.w is not None:
                    layout["w"] = p.w
                if p.h is not None:
                    layout["h"] = p.h
                item["layout"] = layout
                found = True
                break
        if not found:
            raise ValueError(f"Component '{p.component_id}' not found")
        resp = await ctx.client._request_with_retries(
            "POST",
            f"/api/v1/custom-reports/{p.report_id}/versions",
            auth=ctx.auth,
            params={"workspace_id": ws},
            json_body={"definition": definition},
        )
        return self.wrap_result(ctx.client.raise_for_status(resp), _te(ctx))


class ValidateReportTool(BaseTool):
    name: ClassVar[str] = "validate_report"
    description: ClassVar[str] = (
        "Validate a Universal Report Builder DSL definition (or the latest draft for "
        "report_id). Rejects SQL/code keys and unknown datasets. Read-only."
    )

    @classmethod
    def input_schema(cls) -> dict[str, Any]:
        return ValidateReportParams.model_json_schema()

    async def run(self, ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
        p = validate_args(params, ValidateReportParams)
        ws = ctx.auth.workspace_id
        definition = p.definition
        if definition is None:
            if p.report_id is None:
                raise ValueError("definition or report_id is required")
            report_resp = await ctx.client._request_with_retries(
                "GET",
                f"/api/v1/custom-reports/{p.report_id}",
                auth=ctx.auth,
                params={"workspace_id": ws},
            )
            report = ctx.client.raise_for_status(report_resp)
            versions = ((report.get("data") or report) if isinstance(report, dict) else {}).get("versions") or []
            draft = next((v for v in versions if v.get("status") == "draft"), versions[0] if versions else None)
            definition = (draft or {}).get("definition") or {}
        resp = await ctx.client._request_with_retries(
            "POST",
            "/api/v1/custom-reports/validate",
            auth=ctx.auth,
            json_body={"workspace_id": ws, "definition": definition},
        )
        return self.wrap_result(ctx.client.raise_for_status(resp), _te(ctx))


class PreviewReportTool(BaseTool):
    name: ClassVar[str] = "preview_report"
    description: ClassVar[str] = (
        "Preview a custom report definition or existing report_id without publishing. "
        "Returns per-component data. Read-only against live CRM sources."
    )

    @classmethod
    def input_schema(cls) -> dict[str, Any]:
        return PreviewReportParams.model_json_schema()

    async def run(self, ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
        p = validate_args(params, PreviewReportParams)
        if p.report_id is None and p.definition is None:
            raise ValueError("definition or report_id is required")
        if p.report_id is None:
            resp = await ctx.client._request_with_retries(
                "POST",
                "/api/v1/custom-reports/preview",
                auth=ctx.auth,
                json_body={
                    "workspace_id": ctx.auth.workspace_id,
                    "definition": p.definition,
                    "context": p.context or {},
                },
            )
            return self.wrap_result(ctx.client.raise_for_status(resp), _te(ctx))
        resp = await ctx.client._request_with_retries(
            "POST",
            f"/api/v1/custom-reports/{p.report_id}/preview",
            auth=ctx.auth,
            params={"workspace_id": ctx.auth.workspace_id},
            json_body={"definition": p.definition, "context": p.context or {}},
        )
        return self.wrap_result(ctx.client.raise_for_status(resp), _te(ctx))


class PublishReportTool(BaseTool):
    name: ClassVar[str] = "publish_report"
    description: ClassVar[str] = (
        "Publish the current draft of a custom report. Customer assignments stay pinned "
        "to the previous published version until reassigned."
    )

    @classmethod
    def input_schema(cls) -> dict[str, Any]:
        return PublishReportParams.model_json_schema()

    async def run(self, ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
        p = validate_args(params, PublishReportParams)
        if ctx.settings.dry_run:
            return self.wrap_result({"dry_run": True, "would_publish": True}, _te(ctx))
        body: dict[str, Any] = {}
        if p.version_id:
            body["version_id"] = str(p.version_id)
        resp = await ctx.client._request_with_retries(
            "POST",
            f"/api/v1/custom-reports/{p.report_id}/publish",
            auth=ctx.auth,
            params={"workspace_id": ctx.auth.workspace_id},
            json_body=body,
        )
        return self.wrap_result(ctx.client.raise_for_status(resp), _te(ctx))
