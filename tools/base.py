"""Base tool: schema metadata + structured logging + latency tracking."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, ClassVar

from pydantic import BaseModel, ValidationError

from log_sanitize import safe_log_json

if TYPE_CHECKING:
    from middleware import ToolContext

logger = logging.getLogger("crm_mcp.tools")


class ToolMeta(BaseModel):
    model_config = {"extra": "forbid"}

    name: str
    version: str = "1.0.0"
    description: str


class ToolExecuteContext(BaseModel):
    model_config = {"extra": "forbid"}

    user_id: str
    workspace_id: str
    request_id: str


class BaseTool(ABC):
    name: ClassVar[str]
    version: ClassVar[str] = "1.0.0"
    description: ClassVar[str]

    @abstractmethod
    async def run(self, ctx: "ToolContext", params: dict[str, Any]) -> dict[str, Any]:
        """Execute tool and return { data, _meta } envelope."""

    @classmethod
    @abstractmethod
    def input_schema(cls) -> dict[str, Any]:
        ...

    @classmethod
    def mcp_tool(cls, input_schema: dict[str, Any]) -> dict[str, Any]:
        return {
            "name": cls.name,
            "description": cls.description,
            "inputSchema": input_schema,
        }

    def wrap_result(self, data: Any, ctx: ToolExecuteContext) -> dict[str, Any]:
        return {
            "data": data,
            "_meta": {
                "workspace_id": ctx.workspace_id,
                "tool_version": self.version,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "request_id": ctx.request_id,
            },
        }

    def log_event(
        self,
        status: str,
        *,
        workspace_id: str,
        user_id: str,
        request_id: str,
        latency_ms: float,
        tool: str,
    ) -> None:
        payload = {
            "event": "tool_invoked",
            "tool": tool,
            "workspace_id": workspace_id,
            "user_id": user_id,
            "request_id": request_id,
            "latency_ms": round(latency_ms, 3),
            "status": status,
        }
        logger.info(safe_log_json(payload))


def validate_args(params: dict[str, Any], model: type[BaseModel]) -> BaseModel:
    try:
        return model.model_validate(params)
    except ValidationError as e:
        raise ValueError(str(e)) from e
