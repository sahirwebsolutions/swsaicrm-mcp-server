"""Structured logging for MCP tools (write paths + request-level audit)."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from canonical import canonical_json
from log_sanitize import safe_log_json

_write_logger = logging.getLogger("crm_mcp.write")


def params_fingerprint(params: dict[str, Any]) -> str:
    """Short stable fingerprint of normalized tool arguments (SHA-256 prefix)."""
    digest = hashlib.sha256(canonical_json(params).encode("utf-8")).hexdigest()
    return digest[:16]


def log_mcp_tool_audit(
    logger: logging.Logger,
    *,
    tool: str,
    request_id: str,
    outcome: str,
    params_fp: str,
    user_id: str | None,
    workspace_id: str | None,
) -> None:
    payload = {
        "event": "mcp_tool_audit",
        "tool": tool,
        "request_id": request_id,
        "outcome": outcome,
        "params_fp": params_fp,
        "user_id": user_id,
        "workspace_id": workspace_id,
    }
    logger.info(json.dumps(payload, ensure_ascii=False))


def log_write_tool_invoked(
    *,
    tool: str,
    idempotency_key: str,
    request_id: str,
    status: str,
    outcome_body: dict[str, Any] | None = None,
) -> None:
    payload: dict[str, Any] = {
        "event": "write_tool_invoked",
        "tool": tool,
        "idempotency_key": idempotency_key,
        "request_id": request_id,
        "status": status,
    }
    if outcome_body is not None:
        payload["outcome"] = outcome_body
    _write_logger.info(safe_log_json(payload))


def log_write_result(
    *,
    tool: str,
    resource_id: str | None,
    idempotency_key: str,
    request_id: str,
) -> None:
    payload = {
        "event": "write_tool_result",
        "tool": tool,
        "resource_id": resource_id,
        "idempotency_key": idempotency_key,
        "request_id": request_id,
    }
    _write_logger.info(safe_log_json(payload))
