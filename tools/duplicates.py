"""Duplicate-contact pre-check — FastAPI /api/v1/contacts?search=.

Call this BEFORE create_contact so the AI can avoid creating a duplicate. Matches by
email, then phone, then name (most→least reliable). Read-only.
"""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, Field, model_validator

from middleware import ToolContext
from tools.base import BaseTool, ToolExecuteContext, validate_args


class CheckDuplicatesParams(BaseModel):
    model_config = {"extra": "forbid"}

    email: str | None = Field(None, max_length=320)
    phone: str | None = Field(None, max_length=64)
    name: str | None = Field(None, max_length=255)

    @model_validator(mode="after")
    def _at_least_one(self) -> "CheckDuplicatesParams":
        if not any([self.email, self.phone, self.name]):
            raise ValueError("Provide at least one of email, phone, or name.")
        return self


class CheckDuplicatesTool(BaseTool):
    name: ClassVar[str] = "check_duplicates"
    description: ClassVar[str] = (
        "Use BEFORE creating a contact to check whether one already exists with the same "
        "email, phone, or name. Returns any likely matches so you can update instead of "
        "duplicating. Read-only."
    )

    @classmethod
    def input_schema(cls) -> dict[str, Any]:
        return CheckDuplicatesParams.model_json_schema()

    async def _search(self, ctx: ToolContext, ws: str, term: str) -> list[dict[str, Any]]:
        resp = await ctx.client._request_with_retries(
            "GET",
            "/api/v1/contacts",
            auth=ctx.auth,
            params={"workspace_id": ws, "search": term, "limit": 5},
        )
        body = ctx.client.raise_for_status(resp)
        rows = body.get("data") if isinstance(body, dict) else body
        return [r for r in (rows or []) if isinstance(r, dict)]

    async def run(self, ctx: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
        p = validate_args(params, CheckDuplicatesParams)
        ws = ctx.auth.workspace_id

        matched_by: str | None = None
        matches: list[dict[str, Any]] = []
        for field, term in (("email", p.email), ("phone", p.phone), ("name", p.name)):
            if not term:
                continue
            found = await self._search(ctx, ws, str(term).strip())
            if found:
                matched_by = field
                matches = found
                break

        slim = [
            {
                "id": m.get("id"),
                "name": (
                    m.get("name")
                    or " ".join(
                        x for x in [m.get("first_name"), m.get("last_name")] if x
                    ).strip()
                    or None
                ),
                "email": m.get("email"),
                "phone": m.get("phone") or m.get("phone_number"),
                "status": m.get("status"),
            }
            for m in matches
        ]
        te = ToolExecuteContext(
            user_id=ctx.auth.user_id,
            workspace_id=ctx.auth.workspace_id,
            request_id=ctx.request_id,
        )
        return self.wrap_result(
            {
                "is_duplicate": bool(slim),
                "matched_by": matched_by,
                "count": len(slim),
                "matches": slim,
            },
            te,
        )
