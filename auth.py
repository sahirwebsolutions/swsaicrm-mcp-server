"""JWT validation (python-jose). Extract user_id and workspace_id for upstream headers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from jose import jwt
from jose.exceptions import ExpiredSignatureError, JWTError


@dataclass(frozen=True)
class AuthContext:
    """Resolved JWT identity for one MCP request/session."""

    token: str
    user_id: str
    workspace_id: str


class AuthError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def decode_bearer_jwt(bearer_token: str, *, secret: str, algorithms: list[str]) -> AuthContext:
    """
    Validate HS* JWT and extract CRM identity.

    Expects (at minimum):
    - `profile_id` → user_id (CRM user_profiles.id)
    - `workspace_id` → tenancy (reject if missing per product MCP rules)
    """
    token = (bearer_token or "").strip()
    if not token:
        raise AuthError("auth_failed", "missing bearer token")

    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            secret,
            algorithms=algorithms,
            options={"verify_aud": False},
        )
    except ExpiredSignatureError as e:
        raise AuthError("auth_failed", "token expired") from e
    except JWTError as e:
        raise AuthError("auth_failed", "invalid token") from e

    if payload.get("type") != "access":
        raise AuthError("auth_failed", "invalid token type")

    user_id = payload.get("profile_id") or payload.get("user_id")
    if not user_id or str(user_id).strip() == "":
        raise AuthError("auth_failed", "missing profile_id in token")

    workspace_id = payload.get("workspace_id") or payload.get("current_workspace_id")
    if not workspace_id or str(workspace_id).strip() == "":
        raise AuthError("auth_failed", "missing workspace_id in token")

    return AuthContext(
        token=token,
        user_id=str(user_id).strip(),
        workspace_id=str(workspace_id).strip(),
    )


def auth_headers(ctx: AuthContext, request_id: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {ctx.token}",
        "X-User-Id": ctx.user_id,
        "X-Workspace-Id": ctx.workspace_id,
        "X-Request-Id": request_id,
    }
