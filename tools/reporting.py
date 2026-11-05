"""Governed reporting tool — FastAPI /api/v1/reporting + dashboard widgets.

A single ``generate_report`` tool exposing a WHITELIST of pre-built, server-side
aggregations. There is NO arbitrary query/code execution — the AI may only pick a
named report from the catalog and (optionally) a date window. Each report maps to a
governed FastAPI endpoint that already enforces RBAC + workspace scoping. Read-only.
"""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, Field

from date_range import parse_relative_range
from middleware import ToolContext
from tools.base import BaseTool, ToolExecuteContext, validate_args

# report name -> (path, supports_date_range)
_REPORTS: dict[str, tuple[str, bool]] = {
    "contacts_by_source": ("/api/v1/reporting/contacts-by-source", True),
    "contact_creation_trend": ("/api/v1/reporting/contact-creation-trend", True),
    "lead_distribution": ("/api/v1/reporting/lead-distribution", True),
    "deals_aggregate": ("/api/v1/reporting/deals-aggregate", True),
    "deals_by_lead_source": ("/api/v1/reporting/deals-by-lead-source", True),
    "activity_summary": ("/api/v1/reporting/activity-summary", True),
    "appointments_summary": ("/api/v1/reporting/appointments-summary", True),
    "calls_by_rep": ("/api/v1/reporting/calls-by-rep", True),
    "workspace_activity_digest": ("/api/v1/reporting/workspace-activity-digest", True),
    "member_closed_deals_leaderboard": (
        "/api/v1/reporting/member-closed-deals-leaderboard",
        True,
    ),
    "tasks_summary": ("/api/v1/widgets/tasks.metric.summary", False),
    "contacts_total": ("/api/v1/widgets/contacts.metric.total", False),
    "pipeline_value": ("/api/v1/widgets/deals.metric.pipeline_value", False),
    "contacts_statistics": ("/api/v1/contacts/statistics", False),
}

_REPORT_NAMES = sorted(_REPORTS.keys())


class GenerateReportParams(BaseModel):
    model_config = {"extra": "forbid"}

    report: str = Field(..., description="One of the whitelisted report names.")
    date_range: str | None = Field(
        None,
        max_length=64,
        description="Natural language window ('this month', 'last 30 days') for "
        "date-aware reports. Ignored by point-in-time reports.",
    )
    start_date: str | None = Field(None, description="Explicit start date YYYY-MM-DD.")
    end_date: str | None = Field(None, description="Explicit end date YYYY-MM-DD.")


class GenerateReportTool(BaseTool):
    name: ClassVar[str] = "generate_report"
    description: ClassVar[str] = (
        "Use when the user asks for an aggregate/summary/report/analytics number rather "
        "than a list of records — e.g. 'contacts by source', 'pipeline value', 'task "
        "summary', 'calls by rep this month'. Pick a report from the catalog; no custom "
        "queries. Read-only. Available reports: " + ", ".join(_REPORT_NAMES) + "."
    )

    @classmethod
    def input_schema(cls) -> dict[str, Any]:
        schema = GenerateReportParams.model_json_schema()
        # Constrain the report field to the whitelist so the LLM can't invent one.
        schema.setdefault("properties", {}).setdefault("report", {})["enum"] = _REPORT_NAMES
        return schema

    async def run(self, ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
        p = validate_args(params, GenerateReportParams)
        entry = _REPORTS.get(p.report)
        if entry is None:
            raise ValueError(
                f"Unknown report '{p.report}'. Choose one of: {', '.join(_REPORT_NAMES)}."
            )
        path, supports_date = entry
        ws = ctx.auth.workspace_id
        q: dict[str, Any] = {"workspace_id": ws}
        if supports_date:
            start, end = parse_relative_range(
                p.date_range, start=p.start_date, end=p.end_date
            )
            if start:
                q["start_date"] = start
            if end:
                q["end_date"] = end

        key = ctx.cache.key_for(ws, self.name, {"report": p.report, **q})
        hit = ctx.cache.get(key)
        if hit is not None:
            return hit

        resp = await ctx.client._request_with_retries(
            "GET", path, auth=ctx.auth, params=q
        )
        body = ctx.client.raise_for_status(resp)
        te = ToolExecuteContext(
            user_id=ctx.auth.user_id,
            workspace_id=ctx.auth.workspace_id,
            request_id=ctx.request_id,
        )
        out = self.wrap_result({"report": p.report, "result": body}, te)
        ctx.cache.set(key, out)
        return out
