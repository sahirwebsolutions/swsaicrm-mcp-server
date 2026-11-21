"""Invalidate cache entries by CRM scope (namespace), not global nuking."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cache import TtlCache

# scope name → tool cache prefixes `{workspace_id}:{tool_name}:…`
# call_read_action can read any scope, so every write clears it too.
SCOPE_TOOLS: dict[str, tuple[str, ...]] = {
    "tasks": ("list_tasks", "get_task", "call_read_action"),
    "contacts": ("search_contacts", "get_contact", "call_read_action"),
    "boards": ("list_boards", "call_read_action"),
    "deals": ("list_deals", "call_read_action"),
    "pipelines": ("list_pipelines", "call_read_action"),
}


def invalidate_scope(cache: "TtlCache", workspace_id: str, scope: str) -> int:
    tools = SCOPE_TOOLS.get(scope)
    if not tools:
        return 0
    removed = 0
    for tool_name in tools:
        removed += cache.invalidate_prefix(f"{workspace_id}:{tool_name}")
    return removed
