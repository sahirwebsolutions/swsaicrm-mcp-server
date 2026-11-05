"""Shared write-tool helpers: dedupe guard, invalidation, result logging."""

from __future__ import annotations

from typing import Any

from cache_invalidation_map import invalidate_by_tool
from middleware import ToolContext
from resource_id import resource_id_from_response
from tool_logging import log_write_result


def is_unknown_write_outcome(api_body: dict[str, Any]) -> bool:
    """True when the HTTP layer returned a synthetic idempotent-timeout envelope."""
    return api_body.get("status") == "unknown" and "message" in api_body


def guard_try_cached(
    ctx: ToolContext,
    tool_name: str,
    workspace_id: str,
    params_snapshot: dict[str, Any],
) -> dict[str, Any] | None:
    """Return last successful identical write within the dedupe window, or None."""
    if ctx.settings.dry_run:
        return None
    return ctx.write_guard.try_hit(workspace_id, tool_name, params_snapshot)


def finalize_write_success(
    ctx: ToolContext,
    tool_name: str,
    workspace_id: str,
    params_snapshot: dict[str, Any],
    wrapped_result: dict[str, Any],
    idempotency_key: str,
    api_body: dict[str, Any],
) -> None:
    if is_unknown_write_outcome(api_body):
        return
    invalidate_by_tool(ctx.cache, workspace_id, tool_name)
    log_write_result(
        tool=tool_name,
        resource_id=resource_id_from_response(api_body),
        idempotency_key=idempotency_key,
        request_id=ctx.request_id,
    )
    if not ctx.settings.dry_run:
        ctx.write_guard.record(
            workspace_id,
            tool_name,
            params_snapshot,
            wrapped_result,
        )
