"""Tool name → cache scopes for dependency-aware invalidation."""

from __future__ import annotations

from typing import TYPE_CHECKING

from scope_invalidation import invalidate_scope

if TYPE_CHECKING:
    from cache import TtlCache

# Which logical scopes to clear after a write (scopes defined in scope_invalidation.SCOPE_TOOLS).
INVALIDATION_MAP: dict[str, tuple[str, ...]] = {
    "create_deal": ("deals", "pipelines", "contacts"),
    "update_deal": ("deals", "pipelines", "contacts"),
    "update_deal_stage": ("deals", "pipelines", "contacts"),
    "delete_deal": ("deals", "pipelines"),
    "create_pipeline": ("deals", "pipelines", "contacts"),
    "update_pipeline": ("deals", "pipelines", "contacts"),
    "create_board": ("boards", "tasks"),
    "update_board": ("boards", "tasks"),
    "delete_board": ("boards", "tasks"),
    "create_contact": ("contacts",),
    "update_contact": ("contacts", "tasks"),
    "delete_contact": ("contacts", "tasks"),
    "add_contact_note": ("contacts",),
    "create_task": ("tasks", "contacts"),
    "update_task_status": ("tasks", "contacts"),
}


def invalidate_by_tool(cache: "TtlCache", workspace_id: str, tool_name: str) -> int:
    """
    Invalidate read caches affected by this tool.

    Falls back to a single inferred scope when the tool is not listed (prefix heuristic).
    """
    scopes = INVALIDATION_MAP.get(tool_name)
    if scopes is None:
        scopes = _infer_scopes(tool_name)
    total = 0
    for scope in scopes:
        total += invalidate_scope(cache, workspace_id, scope)
    return total


def _infer_scopes(tool_name: str) -> tuple[str, ...]:
    if "deal" in tool_name or "pipeline" in tool_name or "opportunit" in tool_name:
        return ("deals", "pipelines")
    if "contact" in tool_name:
        return ("contacts",)
    if "board" in tool_name:
        return ("boards", "tasks")
    if "task" in tool_name:
        return ("tasks", "contacts")
    return ("deals", "pipelines", "contacts")
