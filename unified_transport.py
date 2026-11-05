"""MCP transport adapter — route INTERNAL tools through unified execute endpoint."""

from __future__ import annotations

import os
from typing import Any

from auth import AuthContext
from client import CRMClient, UpstreamError
from tracing import get_request_id

# Canonical INTERNAL tools registered in CrmUnifiedToolRegistry (MCP alias → canonical)
UNIFIED_INTERNAL_TOOLS: frozenset[str] = frozenset(
    {
        "search_contacts",
        "contacts_search",
        "get_contact",
        "contacts_get",
        "list_tasks",
        "tasks_list",
        "create_task",
        "update_task_status",
        "create_contact",
        "create_deal",
        "send_email",
        "send_whatsapp",
        "make_phone_call",
        "create_calendar_event",
        "update_contact",
        "update_deal_stage",
    }
)


def routes_via_unified_executor(tool_name: str) -> bool:
    if os.getenv("MCP_UNIFIED_EXECUTOR", "1").strip().lower() in ("0", "false", "no"):
        return False
    return tool_name in UNIFIED_INTERNAL_TOOLS


async def execute_via_unified(
    client: CRMClient,
    auth: AuthContext,
    *,
    tool_name: str,
    payload: dict[str, Any],
    confirmation_token: str | None = None,
    ai_employee_id: str | None = None,
) -> dict[str, Any]:
    """POST /api/v1/tools/unified/execute — RBAC/guardrail/audit parity with Copilot."""
    body: dict[str, Any] = {
        "tool_name": tool_name,
        "payload": payload,
    }
    if confirmation_token:
        body["confirmation_token"] = confirmation_token
    if ai_employee_id:
        body["ai_employee_id"] = ai_employee_id
    if get_request_id():
        body["execution_id"] = get_request_id()

    resp = await client._request_with_retries(  # noqa: SLF001 — shared client transport
        "POST",
        "/api/v1/tools/unified/execute",
        auth=auth,
        params={"workspace_id": auth.workspace_id},
        json_body=body,
    )
    try:
        out = CRMClient.raise_for_status(resp)
    except UpstreamError as exc:
        return {"success": False, "error": exc.message, "error_code": exc.code}
    if not isinstance(out, dict):
        return {"success": False, "error": "invalid_unified_response"}
    return {
        "data": out.get("data") or {},
        "_meta": {
            "transport": "unified_executor",
            "resolved_tool": out.get("resolved_tool"),
            "execution_path": out.get("execution_path"),
            "success": out.get("success"),
        },
    }
