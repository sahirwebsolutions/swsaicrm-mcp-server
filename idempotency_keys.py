"""Strong idempotency key derivation for write tools."""

from __future__ import annotations

import hashlib
from typing import Any

from canonical import canonical_json


def compute_stable_update_idempotency_key(
    workspace_id: str,
    tool_name: str,
    tool_version: str,
    resource_id: str,
    operation_type: str,
) -> str:
    """
    Stable idempotency for updates: does not vary with partial payload fields.

    SHA-256 hex of:
    workspace_id:tool_name:tool_version:resource_id:operation_type
    """
    payload = (
        f"{workspace_id}:{tool_name}:{tool_version}:{resource_id}:{operation_type}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compute_idempotency_key(
    workspace_id: str,
    tool_name: str,
    tool_version: str,
    params: dict[str, Any],
) -> str:
    """
    SHA-256 hex of: workspace_id:tool_name:tool_version:canonical_json(params)

    `params` must NOT duplicate workspace_id (it scopes the outer hash only).
    """
    payload = f"{workspace_id}:{tool_name}:{tool_version}:{canonical_json(params)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
